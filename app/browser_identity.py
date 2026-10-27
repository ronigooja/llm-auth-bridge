"""Encrypted, account-scoped Camoufox identity preferences."""

import json
import secrets
import hashlib

from .crypto import decrypt, encrypt
from .db import database
from .queue import Cancelled

PROFILE_VERSION = 4
VIEWPORT = {"width": 1760, "height": 900}
SCREEN = {"width": 1920, "height": 1080}


def generate_profile(used_dimensions: set[tuple[int, int]] | None = None) -> dict:
    """Create native preferences and an independent account identity seed.

    ``used_dimensions`` is retained for callers of version one and is ignored.
    Device separation comes from each account's persistent browser directory;
    unique window dimensions are not a device identity mechanism.
    """
    seed = secrets.token_hex(32)
    return {
        "version": PROFILE_VERSION,
        "identity_seed": seed,
        "browser": {"platform": "windows"},
        # Camoufox consumes this configuration at launch.  Keep it encrypted
        # with the profile and replay it verbatim for every subsequent window.
        # Values are deliberately stable per account; they are not regenerated
        # from the Firefox profile directory.
        "camoufox": _camoufox_config(seed, "windows"),
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
    if profile.get("version") in (1, 2, 3):
        profile = json.loads(json.dumps(profile))
        if profile["version"] == 1:
            profile["context"].update(viewport=dict(VIEWPORT), screen=dict(SCREEN))
        profile["version"] = PROFILE_VERSION
        profile["browser"] = {"platform": profile.get("browser", {}).get("platform", "windows")}
        profile["camoufox"] = _camoufox_config(profile["identity_seed"], profile["browser"]["platform"])
    context_options(profile)
    browser_preferences(profile)
    return profile


def _camoufox_config(seed: str, platform: str) -> dict:
    digest = hashlib.sha256(seed.encode("ascii")).digest()
    width = 1760 + digest[0] % 161
    height = 900 + digest[1] % 81
    return {
        "screen.width": 1920,
        "screen.height": 1080,
        "window.outerWidth": width,
        "window.outerHeight": height,
        "navigator.hardwareConcurrency": 8 + digest[2] % 9,
    }


def browser_preferences(profile: dict) -> dict:
    browser = profile.get("browser")
    if (profile.get("version") != PROFILE_VERSION or not isinstance(browser, dict)
            or set(browser) != {"platform"} or browser["platform"] not in ("windows", "macos")):
        raise ValueError("Invalid browser identity preferences")
    return dict(browser)


def configure_page_identity(context, page, profile: dict):
    """Validate the persisted identity; Camoufox applies it at launch.

    Firefox has no Chromium CDP endpoint.  Identity must therefore be passed
    to Camoufox before the first page is created, rather than patched with
    page-scoped JavaScript after startup.
    """
    del context, page
    browser_preferences(profile)
    if not isinstance(profile.get("camoufox"), dict):
        raise ValueError("Invalid Camoufox identity configuration")


def context_options(profile: dict, *, native_window: bool = False) -> dict:
    """Return supported Firefox context options plus persisted Camoufox config."""
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
    if native_window:
        # Let the headed browser's content follow its real desktop window.
        # Fixed emulation otherwise leaves unused desktop around that window.
        for key in ("viewport", "screen", "device_scale_factor"):
            options.pop(key)
        options["no_viewport"] = True
    options["config"] = json.loads(json.dumps(profile["camoufox"]))
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
