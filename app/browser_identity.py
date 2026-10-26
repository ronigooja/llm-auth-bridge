"""Encrypted account identity preferences; not a complete fingerprint engine."""

import json
import secrets
import re

from .crypto import decrypt, encrypt
from .db import database
from .queue import Cancelled

PROFILE_VERSION = 3
VIEWPORT = {"width": 1760, "height": 900}
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
        "browser": {"platform": "windows"},
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
    if profile.get("version") in (1, 2):
        profile = json.loads(json.dumps(profile))
        if profile["version"] == 1:
            profile["context"].update(viewport=dict(VIEWPORT), screen=dict(SCREEN))
        profile["version"] = PROFILE_VERSION
        profile["browser"] = {"platform": "windows"}
    context_options(profile)
    browser_preferences(profile)
    return profile


def browser_preferences(profile: dict) -> dict:
    browser = profile.get("browser")
    if (profile.get("version") != PROFILE_VERSION or not isinstance(browser, dict)
            or set(browser) != {"platform"} or browser["platform"] not in ("windows", "macos")):
        raise ValueError("Invalid browser identity preferences")
    return dict(browser)


def user_agent_override(profile: dict, version: str) -> dict:
    """Build matching UA / UA-CH / navigator.platform for the running engine.

    OS preferences are stable per account. Browser version follows the actual
    executable; it is never randomized or pinned to a fictitious Chrome build.
    This deliberately makes no claim about fonts, graphics, workers or TLS.
    """
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version):
        raise ValueError("Unsupported Chromium version")
    platform = browser_preferences(profile)["platform"]
    major = version.split(".")[0]
    if platform == "windows":
        os_token, navigator_platform, ch_platform, os_version = (
            "Windows NT 10.0; Win64; x64", "Win32", "Windows", "10.0.0")
    else:
        os_token, navigator_platform, ch_platform, os_version = (
            "Macintosh; Intel Mac OS X 10_15_7", "MacIntel", "macOS", "15.0.0")
    return {
        "userAgent": (f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 "
                      f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"),
        "acceptLanguage": profile["context"]["locale"],
        "platform": navigator_platform,
        "userAgentMetadata": {
            "brands": [{"brand": "Chromium", "version": major},
                       {"brand": "Not_A Brand", "version": "99"}],
            "fullVersionList": [{"brand": "Chromium", "version": version},
                                {"brand": "Not_A Brand", "version": "99.0.0.0"}],
            "fullVersion": version,
            "platform": ch_platform, "platformVersion": os_version,
            "architecture": "x86", "bitness": "64", "model": "",
            "mobile": False, "wow64": False,
        },
    }


def configure_page_identity(context, page, profile: dict):
    """Apply native CDP emulation to the managed page before navigation.

    Keep the session attached for the page lifetime; the browser context owns
    its cleanup. Exceptions must stop navigation rather than silently exposing
    a partial identity. No JavaScript property replacement is installed.
    """
    session = context.new_cdp_session(page)
    product = session.send("Browser.getVersion")["product"]
    version = product.split("/", 1)[-1]
    override = user_agent_override(profile, version)
    session.send("Emulation.setUserAgentOverride", override)
    # CDP UA emulation does not change legacy navigator.platform. Keep that
    # property coherent for documents and ordinary frames. Dedicated Worker
    # globals are intentionally not rewritten by this page-scoped hook.
    platform = override["platform"]
    context.add_init_script(
        "Object.defineProperty(Navigator.prototype, 'platform', "
        + "{get: () => " + json.dumps(platform) + ", configurable: true});"
    )


def context_options(profile: dict, *, native_window: bool = False) -> dict:
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
    if native_window:
        # Let the headed browser's content follow its real desktop window.
        # Fixed emulation otherwise leaves unused desktop around that window.
        for key in ("viewport", "screen", "device_scale_factor"):
            options.pop(key)
        options["no_viewport"] = True
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
