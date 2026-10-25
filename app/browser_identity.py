"""Encrypted account-scoped native browser options, independent of credentials.

This is a stable context profile, not a replacement browser fingerprint engine.
No JavaScript patches, user-agent fabrication, or provider device IDs are used.
"""

import json
import secrets

from .crypto import decrypt, encrypt
from .db import database
from .queue import Cancelled

PROFILE_VERSION = 1
MIN_WIDTH, WIDTH_COUNT = 1200, 720
MIN_HEIGHT, HEIGHT_COUNT = 700, 500
PROFILE_CAPACITY = WIDTH_COUNT * HEIGHT_COUNT


def generate_profile(used_dimensions: set[tuple[int, int]]) -> dict:
    """Allocate a distinct desktop viewport, with a random private identity seed.

    The caller serializes allocation. Only the encrypted profile persists these
    dimensions. A finite capacity fails closed rather than reusing a viewport.
    """
    if len(used_dimensions) >= PROFILE_CAPACITY:
        raise RuntimeError("Browser profile capacity exhausted")
    start = secrets.randbelow(PROFILE_CAPACITY)
    for offset in range(PROFILE_CAPACITY):
        slot = (start + offset) % PROFILE_CAPACITY
        width = MIN_WIDTH + slot % WIDTH_COUNT
        height = MIN_HEIGHT + slot // WIDTH_COUNT
        if (width, height) not in used_dimensions:
            break
    return {
        "version": PROFILE_VERSION,
        "identity_seed": secrets.token_hex(32),
        "context": {
            "viewport": {"width": width, "height": height},
            "screen": {"width": width, "height": height + 80},
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

    BEGIN IMMEDIATE serializes first allocation across workers and targets.
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
            profile = json.loads(decrypt(row["profile_cipher"], key))
            context_options(profile)
            return profile
        used = set()
        for existing in conn.execute("SELECT profile_cipher FROM browser_profiles"):
            options = context_options(json.loads(decrypt(existing["profile_cipher"], key)))
            used.add((options["viewport"]["width"], options["viewport"]["height"]))
        profile = generate_profile(used)
        # Recheck after allocation; an expired owner must not create a profile.
        queue.owned(conn, task["id"], task["execution_id"])
        conn.execute(
            "INSERT INTO browser_profiles(account_id,profile_cipher) VALUES(?,?)",
            (account_id, encrypt(json.dumps(profile), key)),
        )
        return profile
