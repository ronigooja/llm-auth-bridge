"""Downstream credential synchronization. No browser traffic or token exchanges here."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


class IntegrationError(RuntimeError):
    """A fixed safe message, with a conservative remote-write uncertainty flag."""

    def __init__(self, message: str, *, write_possible: bool = False):
        super().__init__(message)
        self.write_possible = write_possible


_EXPECTED = {"cliproxyapi": "codex_oauth", "chatgpt-web-voice": "chatgpt_web"}
_CPA_PATH = "/v0/management/auth-files"


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _route(account: dict) -> dict:
    kind = account.get("route_type")
    if kind == "direct":
        return {"type": "direct"}
    if kind != "proxy" or not isinstance(account.get("proxy"), dict):
        raise IntegrationError(
            "Select an explicit direct or proxy account route before synchronization."
        )
    proxy = account["proxy"]
    try:
        parsed = urlsplit(proxy.get("server", ""))
        if (
            parsed.scheme not in {"http", "https", "socks5", "socks5h"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        ):
            raise ValueError
        if any(c.isspace() for c in proxy["server"]):
            raise ValueError
        username, password = proxy.get("username"), proxy.get("password")
        if password is not None and username is None:
            raise ValueError
        auth = ""
        if username is not None:
            if not isinstance(username, str) or (
                password is not None and not isinstance(password, str)
            ):
                raise ValueError
            auth = quote(username, safe="")
            if password is not None:
                auth += ":" + quote(password, safe="")
            auth += "@"
        server = urlunsplit((parsed.scheme, auth + parsed.netloc, "", "", ""))
    except (ValueError, TypeError, KeyError):
        raise IntegrationError("The account proxy configuration is invalid.") from None
    return {"type": "proxy", "url": server}


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _remote_id(value: str | None, identity: str, kind: str) -> str:
    if value is None:
        value = (
            "bridge-"
            + hashlib.sha256((kind + ":" + identity.casefold()).encode()).hexdigest()[
                :32
            ]
        )
        if kind == "cliproxyapi":
            value += ".json"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or any(
            c
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.@+"
            for c in value
        )
        or value.startswith(".")
        or ".." in value
        or (kind == "cliproxyapi" and not value.endswith(".json"))
    ):
        raise IntegrationError(
            "The stored remote ID is invalid; reconcile the target record before retrying."
        )
    return value


class _Adapter:
    def __init__(self, target: dict, transport=None, sleep=time.sleep):
        self.kind = target.get("kind")
        config = target.get("config", {})
        if self.kind not in _EXPECTED or not isinstance(config, dict):
            raise IntegrationError("Unsupported target kind or configuration.")
        try:
            raw = config.get("base_url", "")
            u = urlsplit(raw)
            if (
                u.scheme not in {"http", "https"}
                or not u.hostname
                or u.username is not None
                or u.password is not None
                or u.query
                or u.fragment
                or (u.scheme == "http" and config.get("allow_http") is not True)
                or any(c.isspace() for c in raw)
                or (u.port is not None and not 1 <= u.port <= 65535)
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise IntegrationError(
                "Set a valid HTTPS target URL, or explicitly enable HTTP for a trusted deployment."
            ) from None
        self.base = raw.rstrip("/")
        self.compat = self.kind == "chatgpt-web-voice"
        headers = {"Accept": "application/json"}
        auth = None
        if self.compat:
            if config.get("compatibility") != "bridge-v1":
                raise IntegrationError(
                    "Voice synchronization requires the documented bridge-v1 compatibility API; native voice APIs cannot verify an explicit route."
                )
            if not _text(config.get("admin_username")) or not _text(
                config.get("admin_password")
            ):
                raise IntegrationError(
                    "Configure the voice administrator username and password."
                )
            auth = httpx.BasicAuth(config["admin_username"], config["admin_password"])
        else:
            if (
                config.get("compatibility") or "cpa-auth-files-v1"
            ) not in {"cpa-auth-files-v1", "cpa-native-oauth-v1"}:
                raise IntegrationError(
                    "Select the documented cpa-auth-files-v1 compatibility contract."
                )
            if not _text(config.get("management_key")):
                raise IntegrationError("Configure the CLIProxyAPI management key.")
            headers["Authorization"] = "Bearer " + config["management_key"]
        self.sleep = sleep
        self.client = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(15, connect=5),
            headers=headers,
            auth=auth,
        )

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        # Only reads are retried here. Writes are reconciled by stable remote ID.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                response = self.client.request(method, self.base + path, **kwargs)
            except httpx.TransportError:
                if attempt + 1 < attempts:
                    self.sleep(0.25 * (attempt + 1))
                    continue
                raise IntegrationError(
                    "Target request failed; retry synchronization to reconcile the remote record."
                ) from None
            if response.status_code in {429, 502, 503, 504} and attempt + 1 < attempts:
                # A long Retry-After ends this attempt instead of blocking the worker.
                try:
                    delay = float(response.headers.get("Retry-After", "0.5"))
                except ValueError:
                    delay = 0.5
                if delay > 2:
                    raise IntegrationError(
                        "Target rate limited or temporarily unavailable; retry later."
                    )
                self.sleep(max(0.25, delay))
                continue
            if response.status_code in {401, 403}:
                raise IntegrationError(
                    "Target authentication failed; check administrator credentials and management access."
                )
            if response.status_code == 429:
                raise IntegrationError(
                    "Target rate limited synchronization; retry later."
                )
            if response.status_code != 404 and not 200 <= response.status_code < 300:
                raise IntegrationError(
                    "Target rejected the request; check its documented compatibility contract."
                )
            return response
        raise IntegrationError("Target request failed.")

    @staticmethod
    def data(response):
        try:
            if len(response.content) > 1024 * 1024:
                raise ValueError
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise IntegrationError(
                "Target returned an incompatible JSON response."
            ) from None

    def check(self):
        if self.compat:
            response = self.request("GET", "/bridge/v1/capabilities")
            data = self.data(response)
            if (
                response.status_code == 404
                or data.get("protocol") != "bridge-v1"
                or data.get("explicit_route") is not True
                or data.get("credential_digest") is not True
            ):
                raise IntegrationError(
                    "Install the documented bridge-v1 compatibility API with explicit route and credential readback support."
                )
        else:
            response = self.request("GET", _CPA_PATH)
            if response.status_code == 404 or not isinstance(
                self.data(response).get("files"), list
            ):
                raise IntegrationError(
                    "CLIProxyAPI management auth-files API is unavailable or incompatible."
                )

    def read(self, remote_id):
        if self.compat:
            response = self.request("GET", "/bridge/v1/accounts/" + remote_id)
        else:
            response = self.request(
                "GET", _CPA_PATH + "/download", params={"name": remote_id}
            )
        return None if response.status_code == 404 else self.data(response)

    def find_by_identity(self, identity):
        """Find one existing CLIProxyAPI auth file by its account email.

        Older installations generated provider-owned filenames. Reusing a
        matching file on the first synchronization prevents creating a second
        credential when the local sync record has not captured its remote ID.
        """
        if self.compat:
            return None
        response = self.request("GET", _CPA_PATH)
        data = self.data(response)
        if response.status_code == 404 or not isinstance(data.get("files"), list):
            raise IntegrationError(
                "CLIProxyAPI auth-files API is unavailable or incompatible."
            )
        matches = [
            item.get("name")
            for item in data.get("files", [])
            if isinstance(item, dict)
            and item.get("type") == "codex"
            and isinstance(item.get("email"), str)
            and item["email"].casefold() == identity.casefold()
        ]
        matches = [name for name in matches if isinstance(name, str) and name]
        if len(matches) > 1:
            raise IntegrationError(
                "Multiple remote credentials match this account; reconcile the target record before retrying."
            )
        return matches[0] if matches else None

    def write(self, remote_id, payload):
        if self.compat:
            return self.request(
                "PUT",
                "/bridge/v1/accounts/" + remote_id,
                json=payload,
                headers={"Idempotency-Key": remote_id + "-" + _digest(payload)},
            )
        return self.request("POST", _CPA_PATH, params={"name": remote_id}, json=payload)


def _prepare(kind, result, account):
    if not isinstance(result, dict) or result.get("credential_type") != _EXPECTED[kind]:
        raise IntegrationError("Credential type does not match this target.")
    identity = result.get("identity")
    if (
        not _text(identity)
        or not _text(account.get("username"))
        or identity.casefold() != account["username"].casefold()
    ):
        raise IntegrationError("Browser identity does not match the selected account.")
    credential = result.get("credential")
    if not isinstance(credential, dict) or not _text(credential.get("access_token")):
        raise IntegrationError("Browser result is missing a usable access token.")
    route = _route(account)
    if kind == "cliproxyapi":
        if any(
            not _text(credential.get(key))
            for key in ("refresh_token", "id_token", "account_id")
        ):
            raise IntegrationError(
                "CLIProxyAPI requires complete Codex OAuth tokens and an account ID from the browser exchange."
            )
        payload = {
            key: credential[key]
            for key in ("access_token", "refresh_token", "id_token", "account_id")
        }
        payload.update(
            type="codex",
            email=identity,
            proxy_url="direct" if route["type"] == "direct" else route["url"],
        )
        expires = result.get("expires_at")
        if expires is not None:
            try:
                payload["expired"] = (
                    datetime.fromtimestamp(float(expires), timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            except (ValueError, TypeError, OverflowError, OSError):
                raise IntegrationError(
                    "Browser credential expiry is invalid."
                ) from None
        return identity, payload
    # Web sessions never export refresh tokens to voice services.
    clean = {"access_token": credential["access_token"]}
    if _text(credential.get("device_id")):
        clean["device_id"] = credential["device_id"]
    return identity, {
        "identity": identity,
        "credential_type": "chatgpt_web",
        "credential": clean,
        "route": route,
        "expires_at": result.get("expires_at"),
    }


def _identity(data, compat):
    return data.get("identity" if compat else "email")


def _matches(data, payload, compat):
    if not data:
        return False
    if compat:
        return (
            data.get("identity") == payload["identity"]
            and data.get("credential_type") == payload["credential_type"]
            and data.get("route") == payload["route"]
            and data.get("credential_digest") == _digest(payload["credential"])
        )
    return all(data.get(key) == value for key, value in payload.items())


def sync_credential(
    target: dict,
    result: dict,
    account: dict,
    remote_id: str | None = None,
    *,
    _transport=None,
    _sleep=time.sleep,
    _on_remote_id=None,
    _checkpoint=None,
) -> dict:
    """Upload and read back a credential; retrying reuses the same remote record.

    ``verified`` attests remote storage identity, route, and credential consistency.
    It does not attest real-account usability; deployment verification remains unverified.
    """
    from .cpa_oauth import NativeOAuth, enabled, PROTOCOL
    if enabled(target):
        native = result.get("native_oauth", {})
        if (result.get("credential_type") != "codex_oauth"
            or result.get("identity", "").casefold() != account.get("username", "").casefold()
            or not isinstance(native, dict) or native.get("protocol") != PROTOCOL):
            raise IntegrationError("Native OAuth session result does not match this target.")
        client = NativeOAuth(target, account, native.get("session_id"), remote_id=remote_id,
                             transport=_transport, sleep=_sleep)
        try:
            return client.commit(_on_remote_id, _checkpoint)
        except IntegrationError as exc:
            exc.write_possible = exc.write_possible or client.write_possible or bool(result.get("_reconcile_only"))
            raise
        finally:
            client.close()
    if result.get("native_oauth"):
        raise IntegrationError("Native OAuth sessions require the native target contract.")
    write_started = False
    historical_write_possible = (
        isinstance(result, dict) and result.get("_reconcile_only") is True
    )
    adapter = None
    try:
        kind = target.get("kind")
        if kind not in _EXPECTED:
            raise IntegrationError("Unsupported target kind.")
        identity, payload = _prepare(kind, result, account)
        adapter = _Adapter(target, _transport, _sleep)
        if adapter.compat:
            adapter.check()
        if remote_id is None:
            remote_id = adapter.find_by_identity(identity)
        rid = _remote_id(remote_id, identity, kind)
        # The queue persists this selected ID before any write. If a later
        # response is lost, retries reconcile the same remote object and keep
        # the existing refresh-token uncertainty rules.
        if _on_remote_id is not None:
            _on_remote_id(rid)
        existing = adapter.read(rid)
        if existing is not None:
            if not adapter.compat and existing.get("type") != "codex":
                raise IntegrationError(
                    "Remote record has an incompatible credential type; reconcile it before retrying."
                )
            found_identity = _identity(existing, adapter.compat)
            if (
                not _text(found_identity)
                or found_identity.casefold() != identity.casefold()
            ):
                raise IntegrationError(
                    "Remote record identity differs; reconcile the stored remote ID before retrying."
                )
        if _matches(existing, payload, adapter.compat):
            return {"remote_id": rid, "verified": True}
        if existing is not None and result.get("_reconcile_only") is True:
            raise IntegrationError(
                "Remote credential or route changed after an earlier synchronization attempt; synchronization remains pending to avoid overwriting rotated credentials."
            )
        write_payload = payload
        if existing is not None and not adapter.compat:
            # CLIProxyAPI auth files can carry runtime settings such as
            # priority, weight, and disabled. A credential refresh should
            # replace the credential fields while retaining those settings.
            write_payload = {**existing, **payload}
        for attempt in range(2):
            failure = None
            try:
                write_started = True
                response = adapter.write(rid, write_payload)
                if response.status_code == 404:
                    raise IntegrationError(
                        "Target write endpoint is unavailable; check its compatibility contract."
                    )
            except IntegrationError as exc:
                failure = exc
            # Even a failed write may have committed. Read before deciding to retry.
            current = adapter.read(rid)
            if _matches(current, payload, adapter.compat):
                return {"remote_id": rid, "verified": True}
            if current is not None:
                found_identity = _identity(current, adapter.compat)
                if (
                    not _text(found_identity)
                    or found_identity.casefold() != identity.casefold()
                ):
                    raise IntegrationError(
                        "Remote record identity differs; reconcile the stored remote ID before retrying."
                    )
                # The server may already have refreshed a just-uploaded token. Never
                # replay the old refresh token over a present, nonmatching record.
                raise IntegrationError(
                    "Remote credential or route differs after synchronization; synchronization remains pending to avoid overwriting rotated credentials."
                )
            if failure is not None:
                # Authentication, rate limits and incompatible contracts must not be retried here.
                raise failure from None
            if attempt == 0:
                adapter.sleep(0.5)
        raise IntegrationError(
            "Target readback did not confirm credential, identity and explicit route; synchronization remains pending."
        )
    except IntegrationError as exc:
        exc.write_possible = (
            exc.write_possible or write_started or historical_write_possible
        )
        raise
    finally:
        if adapter is not None:
            adapter.close()


def test_connection(target: dict, *, _transport=None, _sleep=time.sleep) -> dict:
    """Check management API access without authenticating a real user account."""
    from .cpa_oauth import enabled, ROOT, PROTOCOL
    adapter = _Adapter(target, _transport, _sleep)
    try:
        if enabled(target):
            data = adapter.data(adapter.request("GET", ROOT + "/capabilities"))
            if data.get("protocol") != PROTOCOL or not isinstance(data.get("providers"), list) or "codex" not in data["providers"]:
                raise IntegrationError("Install the cpa-native-oauth-v1 native OAuth API.")
        else:
            adapter.check()
        return {"reachable": True, "verification": "unverified"}
    finally:
        adapter.close()
