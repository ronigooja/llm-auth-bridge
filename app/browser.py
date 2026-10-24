"""Single-worker headed OpenAI browser adapter.

Provider markup and downstream credentials remain unverified until serial real
account acceptance. Unknown pages pause the same browser for human takeover.
No traces, HAR, videos, screenshots, or browser state files are created.
"""

import base64
import hashlib
import json
import math
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .routing import account_route
from .totp import generate_code, seconds_remaining

AUTH_ORIGIN = "https://auth.openai.com"
CHATGPT_ORIGIN = "https://chatgpt.com"
BROWSER_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
]
# Unknown/loading pages and submitted navigation controls need a longer window
# than a password/code form that remains available for review.
TRANSITION_WAIT_SECONDS = 30
CHALLENGE_SETTLE_SECONDS = 4
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"


class BrowserError(RuntimeError):
    """Safe error suitable for API display; never include provider output."""


class ReauthenticationRequired(BrowserError):
    def __init__(self):
        super().__init__("reauth_required")


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
            ...Array.from(document.querySelectorAll('main h1, main h2, body > h1, body > h2')),
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
    if parsed.hostname == "auth.openai.com" and "consent" in parsed.path:
        return "consent"
    return "unknown"


def _submit(page):
    button = _visible(page, 'button[type="submit"]:enabled, input[type="submit"]:enabled')
    if button is None:
        # A sole pending button can become enabled after field validation.
        # Playwright's click waits for that state instead of failing immediately.
        button = _visible(page, 'button[type="submit"], input[type="submit"]')
    if button is None:
        raise BrowserError("Login form requires manual review")
    button.click(timeout=10000)


def _save(context, control):
    control.checkpoint()
    control.save_state(context.storage_state())


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
    data = response.json()
    if not isinstance(data, dict) or not data.get("accessToken"):
        return None
    return session_result(data, username)


def run_login(
    account: dict, target: dict, control, saved_state: dict | None = None
) -> dict:
    """Run one login while the worker holds its global browser lock.

    All provider data is kept in memory. The worker encrypts save_state/result.
    Cancellation and takeover are checked between each bounded browser action.
    """
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import Error as PlaywrightError
    import httpx

    kind = target.get("kind")
    if kind not in ("cliproxyapi", "chatgpt-web-voice"):
        raise BrowserError("Unsupported login target")
    if account.get("_maintenance") and kind != "chatgpt-web-voice":
        raise ReauthenticationRequired()
    control.checkpoint()
    with account_route(account) as route:
        with sync_playwright() as playwright:
            browser = None
            try:
                browser = playwright.chromium.launch(
                    headless=False,
                    chromium_sandbox=True,
                    proxy=route.playwright_proxy,
                    env={**os.environ, "DISPLAY": os.getenv("DISPLAY", ":99")},
                    args=BROWSER_ARGS
                    + (
                        ["--no-proxy-server"]
                        if route.playwright_proxy is None
                        else ["--proxy-bypass-list=<-loopback>"]
                    ),
                )
                context = browser.new_context(
                    storage_state=saved_state,
                    accept_downloads=False,
                    service_workers="block",
                )
                context.set_default_timeout(10000)
                page = context.new_page()
                if hasattr(control, "browser_ready"):
                    control.browser_ready(
                        int(os.getenv("BRIDGE_WEBSOCKIFY_PORT", "6080"))
                    )
                control.phase("browser", "Browser ready")
                captured = []
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
                        authorization_url(state, challenge),
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                else:
                    page.goto(
                        CHATGPT_ORIGIN, wait_until="domcontentloaded", timeout=30000
                    )
                    result = _get_session(context, account["username"])
                    if result:
                        _save(context, control)
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
                while True:
                    control.checkpoint()
                    if captured:
                        code = validate_callback(captured[0], state)
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
                    stage = detect_state(page)
                    marker = (stage, urlsplit(page.url).path)
                    if stage == "login" and marker not in submitted:
                        control.phase("login", "Opening account sign in")
                        _visible(page, 'button[data-testid="login-button"]:enabled').click(
                            timeout=10000
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
                    elif stage == "consent" and marker not in submitted:
                        control.phase("consent", "Confirming requested authorization")
                        _submit(page)
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
                            if stage in ("unknown", "email", "login", "consent")
                            else CHALLENGE_SETTLE_SECONDS
                        )
                        if time.monotonic() - started < settle_seconds:
                            page.wait_for_timeout(500)
                            continue
                        _save(context, control)
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
                        }.get(
                            stage,
                            (
                                "waiting_human",
                                "Review the browser and continue after completing the login step",
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
                raise BrowserError(
                    "Browser authentication failed; review the account and route"
                ) from None
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except PlaywrightError:
                        pass
                if hasattr(control, "browser_closed"):
                    control.browser_closed()
