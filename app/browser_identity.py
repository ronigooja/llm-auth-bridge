"""Encrypted account-scoped native browser options, independent of credentials.

This is a stable context profile, not a replacement browser fingerprint engine.
No JavaScript patches, user-agent fabrication, or provider device IDs are used.
"""

import json
import secrets

from .crypto import decrypt, encrypt
from .db import database
from .queue import Cancelled

PROFILE_VERSION = 2
VIEWPORT = {"width": 1760, "height": 960}
SCREEN = {"width": 1920, "height": 1080}


def generate_profile(used_dimensions: set[tuple[int, int]] | None = None) -> dict:
    """Create native preferences and an independent account identity seed.

    ``used_dimensions`` is retained for callers of version one and is ignored.
    Device separation comes from each account's persistent browser directory;
    unique window dimensions are not a device identity mechanism.
    """
    return {
        "version": PROFILE_VERSION,
        "identity_seed": secrets.token_hex(32),
        "context": {
            "viewport": dict(VIEWPORT),
            "screen": dict(SCREEN),
            "device_scale_factor": 1,
            "locale": "en-US",
            "timezone_id": "UTC",
            "color_scheme": "light",
            "reduced_motion": "no-preference",
            "forced_colors": "none",
            "is_mobile": False,
            "has_touch": False,
        },
    }


def _upgrade_profile(profile: dict) -> dict:
    """Normalize legacy geometry without changing the account seed or prefs."""
    if profile.get("version") == 1:
        profile = json.loads(json.dumps(profile))
        profile["version"] = PROFILE_VERSION
        profile["context"].update(viewport=dict(VIEWPORT), screen=dict(SCREEN))
    context_options(profile)
    return profile


def context_options(profile: dict) -> dict:
    """Return only the supported native Chromium context options, never the seed."""
    if profile.get("version") != PROFILE_VERSION:
        raise ValueError("Unsupported browser profile version")
    # JSON round-trip provides independent nested dictionaries for each context.
    options = json.loads(json.dumps(profile["context"]))
    expected = {
        "viewport", "screen", "device_scale_factor", "locale", "timezone_id",
        "color_scheme", "reduced_motion", "forced_colors", "is_mobile", "has_touch",
    }
    if set(options) != expected:
        raise ValueError("Invalid browser profile options")
    return options


def load_or_create_profile(path, key: bytes, queue, task: dict) -> dict:
    """Commit a profile under the current lease before the caller opens a browser.

    BEGIN IMMEDIATE serializes allocation and upgrades across workers and targets.
    Existing profiles are never regenerated on failure or account/target edits.
    """
    with database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        owned = queue.owned(conn, task["id"], task["execution_id"])
        if owned["cancel_requested"]:
            raise Cancelled()
        account_id = owned["account_id"]
        row = conn.execute(
            "SELECT profile_cipher FROM browser_profiles WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if row:
            existing = json.loads(decrypt(row["profile_cipher"], key))
            profile = _upgrade_profile(existing)
            if profile != existing:
                owned = queue.owned(conn, task["id"], task["execution_id"])
                if owned["cancel_requested"]:
                    raise Cancelled()
                conn.execute(
                    "UPDATE browser_profiles SET profile_cipher=? WHERE account_id=?",
                    (encrypt(json.dumps(profile), key), account_id),
                )
            return profile
        profile = generate_profile()
        # Recheck after allocation; an expired/cancelled owner cannot persist.
        owned = queue.owned(conn, task["id"], task["execution_id"])
        if owned["cancel_requested"]:
            raise Cancelled()
        conn.execute(
            "INSERT INTO browser_profiles(account_id,profile_cipher) VALUES(?,?)",
            (account_id, encrypt(json.dumps(profile), key)),
        )
        return profile
