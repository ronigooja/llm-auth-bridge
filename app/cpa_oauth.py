"""Native OAuth client; provider credentials never cross this interface.

Persist session IDs before start and callback-submitted markers before POST.
Never retry authorization codes. Real-account behavior remains unverified.
"""
from urllib.parse import parse_qs, urlsplit
from .integrations import IntegrationError, _Adapter, _route, _remote_id

PROTOCOL = "cpa-native-oauth-v1"
ROOT = "/v8/management/bridge/oauth"
STATES = {"pending", "exchanging", "staged", "committing", "completed", "cancelled", "expired", "failed", "exchange_uncertain"}


def enabled(target):
    return target.get("kind") == "cliproxyapi" and target.get("config", {}).get("compatibility") == PROTOCOL


class NativeOAuth:
    def __init__(self, target, account, session_id, *, remote_id=None, transport=None, sleep=None):
        if not enabled(target):
            raise IntegrationError("Native OAuth requires the cpa-native-oauth-v1 contract.")
        self.account, self.session_id = account, session_id
        self.write_possible = False
        self.route, self.remote_id = _route(account), remote_id
        self.adapter = _Adapter(target, transport, **({"sleep": sleep} if sleep else {}))
        if (not isinstance(session_id, str) or not session_id or len(session_id) > 128
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in session_id)):
            self.close()
            raise IntegrationError("Native OAuth session reference is invalid.")
        self.path = ROOT + "/sessions/" + session_id

    def close(self):
        self.adapter.close()

    def check(self):
        data = self.adapter.data(self.adapter.request("GET", ROOT + "/capabilities"))
        if data.get("protocol") != PROTOCOL or "codex" not in data.get("providers", []):
            raise IntegrationError("Install the cpa-native-oauth-v1 native OAuth API.")

    def _session(self, response):
        if response.status_code == 404:
            return None
        data = self.adapter.data(response)
        if (data.get("protocol") != PROTOCOL or data.get("session_id") != self.session_id
            or not isinstance(data.get("identity"), str)
            or data["identity"].casefold() != self.account["username"].casefold()
            or data.get("route") != self.route or data.get("state") not in STATES):
            raise IntegrationError("Native OAuth session identity, route or protocol does not match.")
        rid = data.get("remote_id")
        if rid is not None:
            _remote_id(rid, self.account["username"], "cliproxyapi")
        if self.remote_id is not None and rid != self.remote_id:
            raise IntegrationError("Native OAuth remote record does not match.")
        if data["state"] == "pending":
            self.validate_authorization(data)
        return data

    @staticmethod
    def validate_authorization(data):
        try:
            u = urlsplit(data["authorization_url"])
            q = parse_qs(u.query, keep_blank_values=True)
            state = data["provider_state"]
            if (u.scheme != "https" or u.netloc != "auth.openai.com" or u.path != "/oauth/authorize"
                or u.fragment or not isinstance(state, str) or not state
                or q.get("state") != [state] or q.get("response_type") != ["code"]
                or q.get("client_id") != ["app_EMoamEEZ73f0CkXaXp7hrann"]
                or q.get("redirect_uri") != ["http://localhost:1455/auth/callback"]
                or q.get("code_challenge_method") != ["S256"]
                or len(q.get("code_challenge", [])) != 1 or not q["code_challenge"][0]):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise IntegrationError("Native OAuth authorization URL is invalid.") from None

    def get(self):
        return self._session(self.adapter.request("GET", self.path))

    def start(self):
        self.check()
        payload = {"identity": self.account["username"], "route": self.route}
        if self.remote_id is not None:
            payload["remote_id"] = self.remote_id
        return self._session(self.adapter.request("PUT", self.path, json=payload))

    def callback(self, redirect_url, state):
        from .browser import validate_callback
        validate_callback(redirect_url, state)
        try:
            return self._session(self.adapter.request("POST", self.path + "/callback", json={"redirect_url": redirect_url}))
        except IntegrationError:
            return self.get()

    def cancel(self):
        return self._session(self.adapter.request("DELETE", self.path))

    def result(self, session):
        if not session or session["state"] not in {"staged", "committing", "completed"}:
            raise IntegrationError("Native OAuth exchange outcome requires reconciliation; the authorization code will not be replayed.")
        return {"credential_type": "codex_oauth", "identity": session["identity"],
                "native_oauth": {"protocol": PROTOCOL, "session_id": self.session_id},
                "remote_id": session.get("remote_id")}

    def commit(self, on_remote_id=None, checkpoint=None):
        self.check()
        session = self.get()
        if not session:
            raise IntegrationError("Native OAuth session is unavailable; reconcile the target before retrying.")
        rid = session.get("remote_id")
        if not rid:
            raise IntegrationError("Native OAuth did not select a remote record.")
        if on_remote_id:
            on_remote_id(rid)
        if session["state"] in {"staged", "committing"}:
            if checkpoint:
                checkpoint()
            self.write_possible = True
            try:
                self._session(self.adapter.request("POST", self.path + "/commit", json={}))
            except IntegrationError:
                pass
            session = self.get()
        if not session or session["state"] != "completed":
            raise IntegrationError("Native OAuth commit outcome remains pending; retry reconciliation.", write_possible=True)
        self.verify_record(session, rid)
        return {"remote_id": rid, "verified": True}

    def verify_record(self, session, rid):
        proof = session.get("record", {})
        digest = session.get("credential_digest")
        if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(proof, dict) or proof.get("remote_id") != rid
            or not isinstance(proof.get("identity"), str)
            or proof["identity"].casefold() != self.account["username"].casefold()
            or proof.get("route") != self.route or proof.get("credential_digest") != digest):
            raise IntegrationError("Native OAuth record readback does not confirm credential, identity and route.", write_possible=True)
