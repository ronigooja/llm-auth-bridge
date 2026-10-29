"""Single-worker headed OpenAI browser adapter.

Provider markup and downstream credentials remain unverified until serial real
account acceptance. Unknown pages pause the same browser for human takeover.
No traces, HAR, videos, or screenshots are created. Temporary native device
files are archived through the encrypted worker control after Firefox closes.
"""

import base64
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from .browser_device import device_directory
from .browser_identity import configure_page_identity
from .routing import account_route
from .route_timezone import resolve_timezone
from .totp import generate_code, seconds_remaining

AUTH_ORIGIN = "https://auth.openai.com"
CHATGPT_ORIGIN = "https://chatgpt.com"
FIREFOX_ARGS = []
# Unknown/loading pages and submitted navigation controls need a longer window
# than a password/code form that remains available for review.
TRANSITION_WAIT_SECONDS = 30
CHALLENGE_SETTLE_SECONDS = 4
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SESSION_COOKIE_FILE = ".bridge-session-cookies.json"
DEVICE_READY_FILE = ".bridge-device-ready"
SESSION_COOKIE_LIMIT = 2 * 1024 * 1024


class BrowserError(RuntimeError):
    """Safe error suitable for API display; never include provider output."""


class ProviderRejection(BrowserError):
    def __init__(self, code, message):
        self.error_code = code
        super().__init__(message)


class ReauthenticationRequired(BrowserError):
    def __init__(self):
        super().__init__("reauth_required")


_PROVIDER_HOSTS = ("chatgpt.com", "auth.openai.com", "auth0.openai.com")
_AUTH_HOSTS = ("auth.openai.com", "auth0.openai.com")
# Applies to every page: phrases specific enough to never appear in ordinary
# provider markup.
_STRICT_REJECTIONS = (
    ("account_deleted", (
        "deleted or deactivated", "deleted or disabled", "account has been deleted",
        "account was deleted", "account is deleted", "account deleted",
        "已被删除或停用", "已删除或停用", "账号已删除", "账户已删除", "帐号已删除", "帐户已删除",
        "账号已被删除", "账户已被删除", "帐号已被删除", "帐户已被删除",
     ), "OpenAI 已删除或停用此账号，无法继续登录"),
    ("account_deactivated", (
        "account has been deactivated", "account was deactivated", "account is deactivated",
        "account deactivated", "account has been disabled", "account was disabled",
        "账号已停用", "账户已停用", "帐号已停用", "账号已被停用", "账户已被停用", "帐号已被停用",
     ), "OpenAI 已停用此账号，无法继续登录"),
    ("account_suspended", (
        "account has been suspended", "account was suspended", "account is suspended",
        "account suspended", "account has been banned", "account was banned",
        "账号已暂停", "账户已暂停", "账号已被暂停", "账户已被暂停", "账号已被封禁", "账户已被封禁",
     ), "OpenAI 已暂停此账号，无法继续登录"),
)
# Applies only to provider authentication pages, where a generic sentence is
# the page's message rather than user content such as chat titles.
_BROAD_REJECTIONS = (
    ("account_deleted", ("has been deleted", "was deleted", "已被删除"),
     "OpenAI 已删除或停用此账号，无法继续登录"),
    ("account_deactivated", ("has been deactivated", "was deactivated", "已被停用"),
     "OpenAI 已停用此账号，无法继续登录"),
    ("account_suspended", ("has been suspended", "was suspended", "已被暂停", "已被封禁"),
     "OpenAI 已暂停此账号，无法继续登录"),
)
_URL_REJECTIONS = (
    ("account_deleted", r"delet"),
    ("account_deactivated", r"deactivat|disabled"),
    ("account_suspended", r"suspend|banned"),
)


def provider_rejection(page):
    """Classify explicit provider account rejection pages.

    Applies to every observed login page and to browser errors. The provider
    changes its markup and wording frequently, so match visible body text and
    provider error parameters, return a stable code/message, and never expose
    page contents in task history or logs.
    """
    try:
        parsed = urlsplit(page.url)
    except Exception:
        parsed = urlsplit("")
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        text = ""
    text = re.sub(r"\s+", " ", text or "").strip().casefold()
    groups = [_STRICT_REJECTIONS]
    if text and (
        parsed.hostname in _AUTH_HOSTS
        or (parsed.hostname == "chatgpt.com" and parsed.path.startswith(("/auth", "/api/auth")))
    ):
        groups.append(_BROAD_REJECTIONS)
    for group in groups:
        for code, needles, message in group:
            if any(needle.casefold() in text for needle in needles):
                return code, message
    if parsed.hostname in _PROVIDER_HOSTS:
        query = " ".join(
            value for key, value in parse_qsl(parsed.query)
            if key in ("error", "error_code", "reason", "error_description")
        )
        if re.search(r"account|user", query, re.I):
            for code, pattern in _URL_REJECTIONS:
                if re.search(pattern, query, re.I):
                    return code, dict((c, m) for c, _, m in _STRICT_REJECTIONS)[code]
    if parsed.hostname in _AUTH_HOSTS and re.search(
        r"(?:error|deactivat|suspend|disable|blocked|denied|delet)", parsed.path, re.I
    ):
        return "account_rejected", "OpenAI 拒绝了此账号登录，请接管浏览器查看页面"
    return None


def wait_provider_rejection(page, attempts=10):
    """Re-check a page that may still be loading after a browser error."""
    for _ in range(attempts):
        rejection = provider_rejection(page)
        if rejection:
            return rejection
        try:
            page.wait_for_timeout(500)
        except Exception:
            return provider_rejection(page)
    return None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def authorization_url(state: str, challenge: str) -> str:
    return (
        AUTH_ORIGIN
        + "/oauth/authorize?"
        + urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": "openid profile email offline_access",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
            }
        )
    )


def validate_callback(url: str, state: str) -> str:
    try:
        parsed = urlsplit(url)
        expected = urlsplit(REDIRECT_URI)
        if (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme,
            expected.netloc,
            expected.path,
        ):
            raise ValueError
        values = parse_qs(parsed.query, keep_blank_values=True)
        if (
            values.get("state") != [state]
            or len(values.get("code", [])) != 1
            or not values["code"][0]
            or "error" in values
            or parsed.fragment
        ):
            raise ValueError
        return values["code"][0]
    except (ValueError, TypeError):
        raise BrowserError("OAuth callback validation failed") from None


def _claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        value = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, IndexError):
        raise BrowserError("Provider returned an invalid credential") from None


def oauth_result(data: dict, username: str) -> dict:
    try:
        if not isinstance(data, dict):
            raise ValueError
        if not all(
            isinstance(data.get(k), str) and data[k]
            for k in ("access_token", "refresh_token", "id_token")
        ):
            raise ValueError
        claims = _claims(data["id_token"])
        email = claims.get("email")
        if not isinstance(email, str) or email.casefold() != username.casefold():
            raise BrowserError("Authenticated account identity does not match")
        lifetime = float(data["expires_in"])
        if not 0 < lifetime < 366 * 86400:
            raise ValueError
        credential = {
            key: data[key] for key in ("access_token", "refresh_token", "id_token")
        }
        auth = claims.get("https://api.openai.com/auth", {})
        account_id = auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
        if not account_id:
            access_auth = _claims(data["access_token"]).get(
                "https://api.openai.com/auth", {}
            )
            account_id = (
                access_auth.get("chatgpt_account_id")
                if isinstance(access_auth, dict)
                else None
            )
        if not isinstance(account_id, str) or not account_id:
            raise ValueError
        credential["account_id"] = account_id
        return {
            "credential_type": "codex_oauth",
            "credential": credential,
            "expires_at": time.time() + lifetime,
            "identity": email,
        }
    except (ValueError, TypeError, KeyError, OverflowError):
        raise BrowserError("Provider returned an invalid credential") from None


def session_result(data: dict, username: str) -> dict:
    try:
        email = data["user"]["email"]
        if not isinstance(email, str) or email.casefold() != username.casefold():
            raise BrowserError("Authenticated account identity does not match")
        token = data["accessToken"]
        if not isinstance(token, str) or not token:
            raise ValueError
        # Session endpoint establishes token ownership; decode only for expiry.
        claims = _claims(token)
        expires = float(claims["exp"])
        if not math.isfinite(expires) or expires <= time.time():
            raise ValueError
        return {
            "credential_type": "chatgpt_web",
            "credential": {"access_token": token},
            "expires_at": expires,
            "identity": email,
        }
    except (KeyError, ValueError, TypeError, OverflowError):
        raise BrowserError("Provider returned an invalid browser session") from None


def _visible(page, selector):
    locator = page.locator(selector)
    for index in range(locator.count()):
        item = locator.nth(index)
        if item.is_visible():
            return item
    return None


def _editable(page, selector):
    """Skip disabled/readonly transition fields without waiting inside fill()."""
    locator = page.locator(selector)
    for index in range(locator.count()):
        item = locator.nth(index)
        if item.is_visible() and item.is_editable():
            return item
    return None


def _code_kind(field) -> str:
    # Read current challenge instructions, never alternate-method link/button
    # text. Ambiguous/unsupported delivery methods require a manual code.
    instructions = field.evaluate(r"""field => {
        const clean = node => {
            const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
            const text = [];
            while (walker.nextNode()) {
                let parent = walker.currentNode.parentElement;
                let visible = true;
                while (parent) {
                    const style = getComputedStyle(parent);
                    if (parent.matches('a, button, nav, footer, script, style')
                        || style.display === 'none' || style.visibility === 'hidden') {
                        visible = false;
                        break;
                    }
                    parent = parent.parentElement;
                }
                if (visible) text.push(walker.currentNode.textContent);
            }
            return text.join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
        };
        const form = field.closest('form');
        const nodes = [
            ...Array.from(field.labels || []),
            ...Array.from((field.getAttribute('aria-describedby') || '').split(/\s+/))
                .map(id => document.getElementById(id)).filter(Boolean),
            ...Array.from((form || field.parentElement).querySelectorAll('h1, h2, h3, p, [role="heading"]')),
            ...Array.from(document.querySelectorAll('h1, h2, [role="heading"][aria-level="1"], [role="heading"][aria-level="2"]')),
        ];
        return nodes.filter(n => !n.closest('a, button, nav, footer')
            && n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden').map(clean);
    }""")
    text = "\n".join(instructions)
    email = bool(re.search(r"\b(?:email|e-mail|inbox)\b|邮箱|电子邮件", text))
    sms = bool(re.search(r"\b(?:sms|text message|phone)\b|短信|手机", text))
    authenticator = any(
        re.search(
            r"^(?:authenticator(?: app)?(?: code)?|authentication app)$"
            r"|code.*(?:from|in|generated by).*?(?:authenticator|authentication app)"
            r"|(?:use|open|check) (?:your|the) (?:authenticator(?: app)?|authentication app)"
            r"|(?:验证器|身份验证应用).*验证码|验证码.*(?:验证器|身份验证应用)",
            instruction,
        )
        for instruction in instructions
    )
    if authenticator and not (email or sms):
        return "totp"
    if email and not (authenticator or sms):
        return "email_code"
    return "verification_code"


def detect_state(page) -> str:
    """Prioritize the most specific known challenge; unknown markup is manual."""
    parsed = urlsplit(page.url)
    if (
        parsed.hostname not in ("auth.openai.com", "auth0.openai.com", "chatgpt.com")
        or parsed.scheme != "https"
    ):
        return "unknown"
    # A password form can contain code-like fields during page transitions.
    # Never classify a visible password form as a code challenge.
    if _editable(page, 'input[type="password"]'):
        return "password"
    code = _editable(
        page,
        'input[autocomplete="one-time-code"], input[name="code"], input[name="otp"]',
    )
    if code is not None:
        return _code_kind(code)
    if _editable(page, 'input[type="email"], input[name="username"]'):
        return "email"
    if parsed.hostname == "chatgpt.com" and _visible(
        page, 'button[data-testid="login-button"]:enabled'
    ):
        return "login"
    if parsed.hostname == "auth.openai.com" and parsed.path == "/choose-an-account":
        return "account_chooser"
    if parsed.hostname == "auth.openai.com" and "consent" in parsed.path:
        return "consent"
    return "unknown"


def _account_choice(page, username):
    """Return only one exact identity target inside a safe account control.

    Click identity text, never the card center (which can overlap a nested
    remove button). Unknown card markup deliberately requires takeover.
    """
    parsed = urlsplit(page.url)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        "https", "auth.openai.com", "/choose-an-account"
    ):
        return None
    identities = page.get_by_text(re.compile(r"^" + re.escape(username) + r"$", re.I))
    # Resolve once: a Locator could select a different same-text element after
    # validation while control.phase or SPA hydration replaces the original.
    visible = [handle for handle in identities.element_handles() if handle.is_visible()]
    if len(visible) != 1:
        return None
    identity = visible[0]
    safe = identity.evaluate(r"""(node, username) => {
        const control = node.closest('button, a, [role="button"]');
        if (!node.isConnected || !control || node.querySelector('button, a, [role="button"]')
            || control.matches(':disabled, [aria-disabled="true"]')) return false;
        // Ignore nested controls such as the card's remove button. The click
        // target remains the exact identity node outside those controls.
        const walker = document.createTreeWalker(control, NodeFilter.SHOW_TEXT);
        const parts = [];
        while (walker.nextNode()) {
            const parent = walker.currentNode.parentElement;
            if (parent.closest('button, a, [role="button"]') === control
                && parent.getClientRects().length
                && getComputedStyle(parent).visibility !== 'hidden')
                parts.push(walker.currentNode.textContent.trim());
        }
        const text = parts.join(' ');
        const label = [control.getAttribute('aria-label') || '',
            control.getAttribute('title') || '', text].join(' ');
        if (/\b(remove|forget|delete|use another account|create account)\b/i.test(label))
            return false;
        const emails = text.match(/[^\s<>"(),;:]+@[^\s<>"(),;:]+/g) || [];
        if (!emails.length || emails.some(email => email.toLowerCase() !== username.toLowerCase()))
            return false;
        if (control.tagName === 'A') {
            const url = new URL(control.href, location.href);
            if (url.origin !== location.origin) return false;
        }
        return true;
    }""", username)
    return identity if safe else None


def _consent_continue(page):
    """Readiness is an unambiguous enabled Continue, not the URL alone."""
    parsed = urlsplit(page.url)
    if (parsed.scheme != "https" or parsed.netloc != "auth.openai.com"
            or parsed.path not in {"/consent", "/oauth/consent",
                                   "/sign-in-with-chatgpt/codex/consent"}):
        return None
    controls = page.get_by_role("button", name=re.compile(r"^Continue$", re.I))
    # Keep the validated node fixed through the later phase notification/click.
    # A detached handle must fail into review instead of resolving a replacement.
    visible = [handle for handle in controls.element_handles() if handle.is_visible()]
    if len(visible) != 1 or not visible[0].is_enabled():
        return None
    return visible[0]


def _submit(page):
    button = _visible(page, 'button[type="submit"]:enabled, input[type="submit"]:enabled')
    if button is None:
        # A sole pending button can become enabled after field validation.
        # Playwright's click waits for that state instead of failing immediately.
        button = _visible(page, 'button[type="submit"], input[type="submit"]')
    if button is None:
        raise BrowserError("Login form requires manual review")
    # The provider often replaces the document immediately after submission.
    # Do not make Playwright wait for the old document's navigation here; the
    # state loop below observes the resulting provider page and classifies it.
    button.click(timeout=10000, no_wait_after=True)


def _restore_legacy_state(context, state):
    """Migrate a bounded cookie/localStorage export into a new native device.

    The init script is inert outside the exact saved origin and fills missing
    keys only. It is installed only for the first run without a device archive.
    IndexedDB remains owned by native persistence, not this legacy migration.
    """
    try:
        if not isinstance(state, dict) or set(state) - {"cookies", "origins"}:
            raise ValueError
        cookies, origins = state.get("cookies", []), state.get("origins", [])
        if not isinstance(cookies, list) or len(cookies) > 1000:
            raise ValueError
        if not isinstance(origins, list) or len(origins) > 100:
            raise ValueError
        for cookie in cookies:
            if not isinstance(cookie, dict) or not all(
                isinstance(cookie.get(key), str) for key in ("name", "value", "domain", "path")
            ):
                raise ValueError
        entries = {}
        for item in origins:
            if not isinstance(item, dict) or not isinstance(item.get("origin"), str):
                raise ValueError
            origin = item["origin"]
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path or origin != f"{parsed.scheme}://{parsed.netloc}"):
                raise ValueError
            values = item.get("localStorage", [])
            if not isinstance(values, list) or len(values) > 1000 or origin in entries:
                raise ValueError
            entries[origin] = []
            for value in values:
                if (not isinstance(value, dict) or set(value) != {"name", "value"}
                        or not all(isinstance(value[k], str) for k in ("name", "value"))):
                    raise ValueError
                entries[origin].append([value["name"], value["value"]])
        # storage_state(indexed_db=True) also exports IndexedDB payloads. They
        # are not migrated here, so bound only the data we actually restore.
        if len(json.dumps({"cookies": cookies, "origins": entries}).encode()) > 8 * 1024 * 1024:
            raise ValueError
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise BrowserError("Saved browser session is invalid") from None
    if cookies:
        context.add_cookies(cookies)
    if entries:
        context.add_init_script(
            "(() => { const entries = " + json.dumps(entries, ensure_ascii=True)
            + "; if (!Object.prototype.hasOwnProperty.call(entries, location.origin)) return;"
            " for (const [name, value] of entries[location.origin]) {"
            " if (localStorage.getItem(name) === null) localStorage.setItem(name, value); } })();"
        )


def _session_cookies(value):
    """Validate only the session cookies Chromium drops on a clean shutdown."""
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError
    allowed = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite", "partitionKey"}
    for cookie in value:
        if not isinstance(cookie, dict) or set(cookie) - allowed:
            raise ValueError
        if not all(isinstance(cookie.get(k), str) for k in ("name", "value", "domain", "path")):
            raise ValueError
        if not cookie["domain"] or not cookie["path"].startswith("/") or cookie.get("expires") != -1:
            raise ValueError
        if any(type(cookie.get(k)) is not bool for k in ("httpOnly", "secure")):
            raise ValueError
        if cookie.get("sameSite") not in {"Strict", "Lax", "None"}:
            raise ValueError
        if "partitionKey" in cookie and not isinstance(cookie["partitionKey"], str):
            raise ValueError
    return value


def _snapshot_session_cookies(context, directory):
    """Write only session cookies inside the private, encrypted device archive."""
    path = directory / SESSION_COOKIE_FILE
    path.unlink(missing_ok=True)
    cookies = _session_cookies([c for c in context.cookies() if c.get("expires") == -1])
    payload = json.dumps({"version": 1, "cookies": cookies}).encode()
    if len(payload) > SESSION_COOKIE_LIMIT:
        raise ValueError
    # No cached older snapshot may survive a failed refresh and resurrect a
    # logged-out session. The entire parent directory is private and temporary.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)


def _restore_session_cookies(context, directory):
    path = directory / SESSION_COOKIE_FILE
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    except OSError:
        raise BrowserError("Saved device session cookies are invalid") from None
    try:
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError
            payload = stream.read(SESSION_COOKIE_LIMIT + 1)
        if len(payload) > SESSION_COOKIE_LIMIT:
            raise ValueError
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"version", "cookies"} or value["version"] != 1:
            raise ValueError
        cookies = _session_cookies(value["cookies"])
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        raise BrowserError("Saved device session cookies are invalid") from None
    if cookies:
        context.add_cookies(cookies)


def _save(context, control, page=None):
    control.checkpoint()
    state = context.storage_state(indexed_db=True)
    # Keep the last provider URL so a later account-window takeover opens the
    # page that required review instead of resetting to the ChatGPT home page.
    if page is not None:
        current_url = page.url
        parsed = urlsplit(current_url)
        if parsed.hostname in ("chatgpt.com", "auth.openai.com", "auth0.openai.com"):
            state["bridge_review_url"] = current_url
    control.save_state(state)


def _human(control, reason: str, phase: str = "waiting_human") -> str | None:
    result = control.wait_human(reason, phase=phase)
    control.checkpoint()
    return result


def _get_session(context, username: str) -> dict | None:
    response = context.request.get(
        CHATGPT_ORIGIN + "/api/auth/session", timeout=10000, max_redirects=0
    )
    if response.status != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        # Interstitial or error HTML instead of the session JSON is not a
        # session; keep classifying the visible page instead of failing.
        return None
    if not isinstance(data, dict) or not data.get("accessToken"):
        return None
    return session_result(data, username)


def _native_result(client, session, control):
    # A running exchange is polled, never replayed. The worker deadline bounds
    # this loop, including after a process restart or lost callback response.
    while session and session["state"] in {"exchanging"}:
        control.checkpoint()
        time.sleep(0.5)
        session = client.get()
    return client.result(session)


def fit_browser_window(context, page) -> None:
    """Fill the real desktop, including browser chrome, without viewport emulation."""
    # Firefox has no CDP Browser.* window endpoint.  The headed desktop owns
    # placement; this best-effort DOM call requests the available dimensions
    # without coupling the adapter to Chromium's remote debugging protocol.
    del context
    page.evaluate("window.moveTo(screen.availLeft || 0, screen.availTop || 0); window.resizeTo(screen.availWidth, screen.availHeight)")


def run_browser_window(account, control, saved_state=None) -> None:
    """Open this account's persistent browser until its operator closes it."""
    _run_login(account, {"kind": "browser_window"}, control, saved_state)


def run_login(account, target, control, saved_state=None):
    from .cpa_oauth import NativeOAuth, enabled
    if not enabled(target):
        return _run_login(account, target, control, saved_state)
    control.checkpoint()
    reserved = control.native_session()
    client = NativeOAuth(target, account, reserved["session_id"], remote_id=reserved.get("remote_id"))
    try:
        client.check()
        session = client.get()
        if session is None and not reserved["callback_submitted"]:
            control.checkpoint()
            session = client.start()
        if reserved["callback_submitted"] or not session or session["state"] != "pending":
            return _native_result(client, session, control)
        return _run_login(account, target, control, saved_state, client, session)
    finally:
        client.close()


def _run_login(
    account: dict, target: dict, control, saved_state: dict | None = None,
    native=None, native_session=None,
) -> dict | None:
    """Run one login or browser window under the global browser lock.

    The worker encrypts device archives, save_state, and results.
    Cancellation and takeover are checked between each bounded browser action.
    """
    from playwright.sync_api import Error as PlaywrightError
    from camoufox.sync_api import Camoufox
    import httpx

    kind = target.get("kind")
    if kind not in ("cliproxyapi", "chatgpt-web-voice", "browser_window"):
        raise BrowserError("Unsupported login target")
    if account.get("_maintenance") and kind == "cliproxyapi":
        raise ReauthenticationRequired()
    control.checkpoint()
    with account_route(account) as route:
        if account.get("route_type") == "proxy":
            control.phase("route_timezone", "Resolving account route timezone")
            zone = resolve_timezone(route.session, checkpoint=control.checkpoint)
            control.update_timezone(zone)
            account["_browser_profile"]["context"]["timezone_id"] = zone
        # Snapshot only after context.close(), including exception paths.
        with device_directory(account, control) as device:
            context = None
            camoufox_runtime = None
            page = None
            try:
                from .browser_identity import context_options
                options = context_options(account["_browser_profile"], native_window=True)
                camoufox_runtime = Camoufox(
                    user_data_dir=str(device.path),
                    headless=False,
                    persistent_context=True,
                    proxy=route.playwright_proxy,
                    env={**os.environ, "DISPLAY": os.getenv("DISPLAY", ":99")},
                    args=FIREFOX_ARGS,
                    os=account["_browser_profile"]["browser"]["platform"],
                    **options,
                    accept_downloads=False,
                    service_workers="block",
                )
                context = camoufox_runtime.__enter__()
                initialized = (device.path / DEVICE_READY_FILE).is_file()
                if initialized:
                    _restore_session_cookies(context, device.path)
                # Chromium storage_state is intentionally not imported.  The
                # Camoufox profile starts a new Firefox session and requires
                # account reauthorization after migration.
                if not initialized:
                    fd = os.open(device.path / DEVICE_READY_FILE,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    os.close(fd)
                # An archive alone is not proof that first-time migration
                # completed. Publish only initialized devices to the archive.
                device.mark_ready()
                context.set_default_timeout(10000)
                page = context.new_page()
                configure_page_identity(context, page, account["_browser_profile"])
                fit_browser_window(context, page)
                if hasattr(control, "browser_ready"):
                    control.browser_ready(
                        int(os.getenv("BRIDGE_WEBSOCKIFY_PORT", "6080"))
                    )
                control.phase("browser", "Browser ready")
                if kind == "browser_window":
                    review_url = (saved_state or {}).get("bridge_review_url")
                    if not isinstance(review_url, str) or urlsplit(review_url).hostname not in (
                        "chatgpt.com", "auth.openai.com", "auth0.openai.com"
                    ):
                        review_url = CHATGPT_ORIGIN
                    page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
                    _save(context, control, page)
                    _human(control, "Use the account browser, then continue to save and close it",
                           phase="browser_window")
                    _save(context, control, page)
                    return None
                captured = []
                if native:
                    verifier, challenge = None, None
                    state = native_session["provider_state"]
                else:
                    verifier, challenge = pkce_pair()
                    state = secrets.token_urlsafe(32)

                def intercept(request_route):
                    captured.append(request_route.request.url)
                    request_route.fulfill(
                        status=200,
                        content_type="text/plain",
                        body="Authorization received. Return to the bridge.",
                    )

                context.route(REDIRECT_URI + "**", intercept)
                if kind == "cliproxyapi":
                    page.goto(
                        native_session["authorization_url"] if native else authorization_url(state, challenge),
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                else:
                    page.goto(
                        CHATGPT_ORIGIN, wait_until="domcontentloaded", timeout=30000
                    )
                    result = _get_session(context, account["username"])
                    if result:
                        _save(context, control, page)
                        return result
                    if account.get("_maintenance"):
                        raise ReauthenticationRequired()
                    page.goto(
                        CHATGPT_ORIGIN + "/auth/login",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                submitted = set()
                totp_attempts = 0
                manual_rounds = 0
                started = time.monotonic()
                observed_marker = None
                while True:
                    control.checkpoint()
                    if captured:
                        code = validate_callback(captured[0], state)
                        if native:
                            # Fence and persist before network I/O: a lost POST
                            # response or restart must never replay this code.
                            control.native_callback_submitted()
                            control.checkpoint()
                            result = _native_result(native, native.callback(captured[0], state), control)
                            _save(context, control)
                            return result
                        control.phase("token_exchange", "Exchanging authorization code")
                        response = route.session.post(
                            AUTH_ORIGIN + "/oauth/token",
                            data={
                                "grant_type": "authorization_code",
                                "client_id": CLIENT_ID,
                                "code": code,
                                "redirect_uri": REDIRECT_URI,
                                "code_verifier": verifier,
                            },
                        )
                        if response.status_code != 200:
                            raise BrowserError("OAuth token exchange failed")
                        result = oauth_result(response.json(), account["username"])
                        _save(context, control)
                        return result
                    if (
                        kind == "chatgpt-web-voice"
                        and urlsplit(page.url).hostname == "chatgpt.com"
                    ):
                        result = _get_session(context, account["username"])
                        if result:
                            _save(context, control)
                            return result
                    rejection = provider_rejection(page)
                    if rejection:
                        code, reason = rejection
                        _save(context, control, page)
                        _human(control, reason, phase=code)
                        page.wait_for_timeout(500)
                        continue
                    stage = detect_state(page)
                    marker = (stage, urlsplit(page.url).path)
                    if marker != observed_marker:
                        # Allow newly arrived continuation markup a full,
                        # bounded hydration window before human review.
                        observed_marker = marker
                        if stage in ("account_chooser", "consent"):
                            started = time.monotonic()
                    continuation = None
                    if marker not in submitted:
                        try:
                            if stage == "account_chooser" and kind == "cliproxyapi":
                                continuation = _account_choice(page, account["username"])
                            elif stage == "consent":
                                continuation = _consent_continue(page)
                        except PlaywrightError:
                            # DOM replacement during hydration is not a failed
                            # login. Keep observing until the review deadline.
                            continuation = None
                    if stage == "login" and marker not in submitted:
                        control.phase("login", "Opening account sign in")
                        _visible(page, 'button[data-testid="login-button"]:enabled').click(
                            timeout=10000, no_wait_after=True
                        )
                        submitted.add(marker)
                        started = time.monotonic()
                    elif stage in ("email", "password") and marker not in submitted:
                        control.phase(stage, "Submitting account " + stage)
                        selector = (
                            'input[type="email"], input[name="username"]'
                            if stage == "email"
                            else 'input[type="password"]'
                        )
                        _editable(page, selector).fill(
                            account["username" if stage == "email" else "password"]
                        )
                        _submit(page)
                        submitted.add(marker)
                        started = time.monotonic()
                    elif stage == "totp" and account.get("totp") and totp_attempts < 2:
                        # Avoid submitting a code at the end of its validity window.
                        if seconds_remaining() < 5:
                            page.wait_for_timeout(500)
                            continue
                        code = generate_code(account["totp"])
                        if ("totp_code", code) not in submitted:
                            control.phase("totp", "Submitting authenticator code")
                            _editable(
                                page,
                                'input[autocomplete="one-time-code"], input[name="code"], input[name="otp"]',
                            ).fill(code)
                            _submit(page)
                            submitted.add(("totp_code", code))
                            totp_attempts += 1
                            started = time.monotonic()
                        else:
                            # Keep the same challenge open until the next TOTP
                            # window; checkpoint on each half-second iteration.
                            page.wait_for_timeout(500)
                            continue
                    elif continuation is not None:
                        control.phase(stage, "Continuing the matching account session"
                                      if stage == "account_chooser"
                                      else "Confirming requested authorization")
                        try:
                            continuation.click(timeout=2000)
                        except PlaywrightError:
                            # Detached/covered controls and uncertain clicks
                            # require review in this browser, never blind replay.
                            pass
                        submitted.add(marker)
                        started = time.monotonic()
                    else:
                        # Email/login/consent may remain visible while a request
                        # is pending, or disappear during SPA hydration. Pausing
                        # here freezes classification until Continue, so keep
                        # observing these transitions before requesting takeover.
                        # Password/code forms retain their short review window;
                        # submitted credentials are never repeated automatically.
                        settle_seconds = (
                            TRANSITION_WAIT_SECONDS
                            if stage in ("unknown", "email", "login", "consent", "account_chooser")
                            else CHALLENGE_SETTLE_SECONDS
                        )
                        if time.monotonic() - started < settle_seconds:
                            page.wait_for_timeout(500)
                            continue
                        _save(context, control, page)
                        phase, reason = {
                            "verification_code": (
                                "verification_code_required",
                                "Enter the verification code shown by the current challenge or take over the browser",
                            ),
                            "email_code": (
                                "email_code_required",
                                "Enter the email verification code or take over the browser",
                            ),
                            "totp": (
                                "authenticator_code_required",
                                "Enter an authenticator code or take over the browser",
                            ),
                            "password": (
                                "password_required",
                                "The password page is still open; review the password or provider error in the browser, then continue",
                            ),
                            "account_chooser": (
                                "waiting_human",
                                "Review the browser and continue after completing the login step",
                            ),
                            "consent": (
                                "waiting_human",
                                "Review the browser and continue after completing the login step",
                            ),
                        }.get(
                            stage,
                            (
                                "browser_review",
                                "Browser page requires manual review; take over the browser or cancel this task",
                            ),
                        )
                        code = _human(control, reason, phase)
                        # Takeover can navigate away while a command is pending.
                        # A code applies only to the challenge that requested it.
                        if (
                            code
                            and stage in ("email_code", "totp", "verification_code")
                            and detect_state(page) == stage
                        ):
                            if (
                                not code.isascii()
                                or not code.isdigit()
                                or len(code) not in (6, 8)
                            ):
                                raise BrowserError(
                                    "Verification code must contain six or eight digits"
                                )
                            field = _editable(
                                page,
                                'input[autocomplete="one-time-code"], input[name="code"], input[name="otp"]',
                            )
                            if field is None:
                                raise BrowserError(
                                    "No supported verification code field is available"
                                )
                            field.fill(code)
                            _submit(page)
                        manual_rounds += 1
                        if manual_rounds > 30:
                            raise BrowserError(
                                "Login requires a new task after repeated manual steps"
                            )
                        started = time.monotonic()
                    page.wait_for_timeout(500)
            except (PlaywrightError, httpx.HTTPError, json.JSONDecodeError):
                # A rejection page often arrives as a redirect that aborts the
                # pending navigation or click; let it finish loading first.
                rejection = wait_provider_rejection(page) if page is not None else None
                if rejection:
                    code, reason = rejection
                    raise ProviderRejection(code, reason) from None
                if page is not None:
                    _save(context, control, page)
                    stage = detect_state(page)
                    _human(
                        control,
                        "Browser navigation or page action failed and no account rejection was recognized; "
                        "take over the browser to inspect the current page",
                        phase="browser_review" if stage == "unknown" else "waiting_human",
                    )
                    rejection = provider_rejection(page)
                    if rejection:
                        code, reason = rejection
                        raise ProviderRejection(code, reason) from None
                raise BrowserError(
                    "Browser authentication failed; review the account and route"
                ) from None
            finally:
                original_failure = sys.exception()
                cleanup_failure = None
                if context is not None:
                    try:
                        _snapshot_session_cookies(context, device.path)
                    except Exception:
                        # Cleanup must never replace cancellation, lease loss,
                        # or provider errors. A successful task must not claim
                        # a saved device when its session snapshot failed.
                        cleanup_failure = BrowserError("Browser device session could not be saved")
                    finally:
                        try:
                            context.close()
                        except Exception:
                            device.abort_snapshot()
                            cleanup_failure = BrowserError("Browser device could not close")
                        if camoufox_runtime is not None:
                            try:
                                camoufox_runtime.__exit__(None, None, None)
                            except Exception:
                                device.abort_snapshot()
                                cleanup_failure = BrowserError("Browser runtime could not close")
                if hasattr(control, "browser_closed"):
                    try:
                        control.browser_closed()
                    except Exception:
                        cleanup_failure = BrowserError("Browser device status could not close")
                if cleanup_failure is not None and original_failure is None:
                    raise cleanup_failure
