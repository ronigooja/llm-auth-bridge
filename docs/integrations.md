# Integrations

Both adapters are **unverified with real accounts**. Mock contract tests verify serialization, stable remote IDs, transport failure reconciliation, identity and explicit route readback, credential type separation, and safe errors. A successful management connection test does not verify account usability.

`sync_credential(target, result, account, remote_id=None)` returns `{remote_id, verified: true}` only after remote readback confirms identity, credential contents (or a digest), and the account's explicit route. Here `verified` describes synchronization consistency, not deployment acceptance or a real upstream account probe. The worker owns encrypted pending results and refresh-token deletion after success. `IntegrationError.write_possible` defaults to false and becomes true before a write starts. On fresh-attempt preflight errors it remains false, allowing the worker to reset its durable attempt counter safely. When the incoming result has `_reconcile_only: true`, all integration errors retain `write_possible: true`, including configuration or connection failures, because a previous attempt may have committed. Unknown exception types must retain durable write uncertainty. The adapters never perform login, OAuth code exchange, token refresh, or a live account probe.

## Target configuration and HTTP

All targets require `base_url`. HTTPS is required unless `allow_http: true` explicitly permits HTTP in a trusted deployment. URLs must not contain user information, query parameters, or fragments. A base path is supported. HTTP requests use a separate client with `trust_env=False`, TLS verification, redirects disabled, a five-second connection timeout, and a fifteen-second operation timeout. The account proxy is serialized into the remote account; it is never used to access the target management API. Targets need independent network reachability from the bridge worker.

GET requests have at most three attempts for transient transport errors, HTTP 429, 502, 503, and 504. Numeric `Retry-After` values above two seconds fail with a retry-later message; smaller values use a bounded delay. Long or date-form delays do not block the worker. Writes use a stable ID and are followed by readback even after a lost response. No unbounded retry loop is used. Remote bodies, URLs containing secrets, HTTP exception text, and credentials are not included in adapter errors or logs.

An account must declare `route_type: direct` or `route_type: proxy`. An absent proxy is never interpreted as direct. Proxy configuration uses `{server, username?, password?}`, with server schemes `http`, `https`, `socks5`, or `socks5h`; proxy credentials are URL encoded for downstream serialization.

## CLIProxyAPI native auth-files contract

Configuration:

```json
{
  "base_url": "https://cpa.example.test",
  "management_key": "<management key>",
  "compatibility": "cpa-auth-files-v1"
}
```

`compatibility` defaults to `cpa-auth-files-v1` when absent or null. Management requests use `Authorization: Bearer <management_key>`:

- Connection test: `GET /v0/management/auth-files`, requiring an object with a `files` array.
- Read/reconciliation: `GET /v0/management/auth-files/download?name=<remote_id>`; HTTP 404 means the named record does not exist.
- Create/update: `POST /v0/management/auth-files?name=<remote_id>` with raw JSON. The same filename overwrites that record.

Only browser results typed `codex_oauth` are accepted. The payload includes `type: codex`, `email`, `access_token`, `refresh_token`, `id_token`, `account_id`, optional RFC 3339 `expired`, and `proxy_url`. The browser must have completed its PKCE exchange through the account route. Direct accounts use the explicit `proxy_url: "direct"` sentinel; proxied accounts use a full validated proxy URL. Blank `proxy_url` would inherit the downstream global proxy and is never emitted or accepted as proof of direct routing.

New filenames are `bridge-<32-character identity/kind hash>.json`; usernames and credentials do not appear in filenames. Existing persisted filenames are reused after strict filename validation. A preexisting record with a different identity is never overwritten. Downloaded JSON must match every emitted field before synchronization succeeds. On a subsequent worker attempt, the worker passes `result["_reconcile_only"] = true`: an existing mismatched credential or route then produces a safe pending conflict and is never overwritten, because the remote service may have rotated its refresh token after a lost response. An absent record can still be uploaded. A fresh browser authorization may intentionally replace an existing record for the same identity. After any write, a present but mismatched record immediately stops synchronization without a second write; a freshly rotated token must not be replaced by the old local token. This verifies stored configuration; it does not prove the downstream service's actual egress IP, runtime policy overrides, or account usability. Deployments must separately accept their downstream runtime behavior.

Public source reviewed on 2026-10-23: [router-for-me/CLIProxyAPI at d946c4f](https://github.com/router-for-me/CLIProxyAPI/tree/d946c4fba6fc9a5cfbca1f3d85184d62ad2fb683), particularly `internal/api/handlers/management/auth_files_crud.go`, `internal/auth/codex/token.go`, `internal/watcher/synthesizer/file.go`, `sdk/proxyutil/proxy.go`, and `internal/runtime/executor/helps/proxy_helpers.go`. These establish raw JSON upload/download, token storage fields, per-account `proxy_url`, and the explicit `direct` sentinel. Older or modified servers may differ; incompatible responses fail closed.

## chatgpt-web-voice compatibility API

The public projects with this name do not currently expose a native contract sufficient for this bridge's verification requirement:

- [dyhhhhhh/chatgpt-web-voice at 9eb6152](https://github.com/dyhhhhhh/chatgpt-web-voice/tree/9eb61526118d272beeb20ed18c0df071274d73e8) has voice-session endpoints and a JSON account pool, but no administrator account CRUD API.
- [Space3044/chatgpt-web-voice at 6338ac4](https://github.com/Space3044/chatgpt-web-voice/tree/6338ac478070aaa34bfe7a3c0469caf9e9174c02) exposes `GET/POST /api/accounts`, `PUT/DELETE /api/accounts/{id}`, and `POST /api/accounts/{id}/check`. Its account views expose token previews and masked `proxy_preview`, rather than exact credentials and routes. A token probe does not establish an explicit direct route or exact proxy credentials.

Consequently native voice synchronization is unsupported and fails with an actionable error. The bridge does **not** assume that either public project implements the following compatibility API. To enable synchronization, an independently implemented server-side compatibility layer must provide it and map it to the target's account store and explicit routing behavior. This repository provides the HTTP client only. This path remains unverified and requires acceptance against the deployed compatibility layer.

Configuration explicitly opts into that contract:

```json
{
  "base_url": "https://voice.example.test",
  "admin_username": "<administrator>",
  "admin_password": "<password>",
  "compatibility": "bridge-v1"
}
```

Requests use HTTP Basic administrator authentication. The service must implement:

1. `GET /bridge/v1/capabilities` returns `{protocol: "bridge-v1", explicit_route: true, credential_digest: true}`. The client checks these capabilities before writing any credential.
2. `PUT /bridge/v1/accounts/{remote_id}` atomically creates or updates that exact remote ID. It must be idempotent, with no duplicate generated IDs. The `Idempotency-Key` request header combines remote ID and payload SHA-256. A write body contains `identity`, `credential_type: "chatgpt_web"`, `credential: {access_token, device_id?}`, `route`, and `expires_at`. `route` is `{type: "direct"}` or `{type: "proxy", url: "<full proxy URL>"}`. Direct must bypass inherited proxy settings. Voice payloads exclude refresh tokens.
3. `GET /bridge/v1/accounts/{remote_id}` returns HTTP 404 when absent, otherwise `{identity, credential_type, route, credential_digest}`. `route` must report the applied explicit configuration, including full proxy authentication for authenticated management callers. `credential_digest` is lowercase SHA-256 of the actual stored credential object encoded as sorted-key, compact UTF-8 JSON with unescaped non-ASCII characters. It must be computed from persisted state, not merely copied from an incoming client claim. The GET must be consistent with an acknowledged PUT.

The new remote ID is `bridge-<32-character identity/kind hash>`. A provided stored remote ID is reused, and readback reconciles a committed write whose response was lost. Identity conflicts stop synchronization. Missing or weaker readback fields stop synchronization; a preview, token liveness probe, or empty proxy does not count as proof.

### Server implementation requirements

For voice accounts, the generated ID is `bridge-` followed by the first 32 hex characters of SHA-256 over UTF-8 `chatgpt-web-voice:<casefolded identity>`. Existing IDs must remain stable across restarts and updates. A server with numeric account IDs needs a durable, atomic mapping to that actual account row. Acknowledged writes and their mapping must survive restart together. Existing mappings must never be reassigned to a different identity. Same-identity replacement after fresh authorization is allowed; a reconciliation attempt stops on a changed credential or route. A server should reject conflicting identities with HTTP 409, without changing either account. If the underlying store deduplicates access tokens, a token already owned by another account also needs a safe conflict rather than a duplicate or reassignment.

The idempotency digest covers the **entire PUT body**, while the readback digest covers only the **stored credential object**. Both use sorted object keys, compact JSON, UTF-8, unescaped non-ASCII characters, and no trailing newline. Do not normalize credential strings or proxy URLs. In particular, Go's default JSON encoding escapes `<`, `>`, `&`, U+2028, and U+2029 and is not byte-compatible with this contract. A cross-language credential vector is:

```text
JSON representation: {"access_token":"synthetic","device_id":"测试<&>\u2028\u2029"}
SHA-256: 5fcc9d4ab814aedce4447a6dd1243d8f67353cf8270f4d23eeaef6aa6286502d
```

In the hashed bytes, the displayed `\u2028` and `\u2029` stand for the literal Unicode separator characters, not six-character escape sequences. Readback must recompute this digest from decrypted persisted credentials; storing a caller's digest or request body as a shadow record does not verify the account used by the voice runtime.

`device_id` is optional. The current browser session extraction emits only `access_token`; the adapter forwards a nonempty `device_id` when a result provides one. A server accepting `device_id` must persist it and use it for that account's upstream device header. An omitted device ID must stay absent in the digest even if the runtime uses its configured default. Servers must reject unsupported credential fields rather than silently reporting a digest for unused data.

The reviewed Space3044 runtime inherits process proxy configuration when an account's proxy is empty. Supporting `{type: "direct"}` therefore requires an explicit bypass in every supported upstream transport, including Go HTTP, TLS client, and curl. Persisting an empty proxy and echoing `direct` is insufficient. Proxy routes must retain the complete URL, including encoded authentication, in both applied configuration and authenticated readback. Existing masked management account views can remain masked; this bridge endpoint requires complete route readback.

Capability, account PUT, and account GET handlers must never call account token checks, session creation, refresh, or other provider endpoints. HTTP Basic authentication must protect all three, and must work without a browser cookie or CSRF token. Storage consistency verification remains distinct from real-account and runtime egress acceptance.

### Disposable synthetic HTTP acceptance

`tests/test_voice_bridge_acceptance.py` exercises the real bridge client over HTTP against an independently started, disposable server. It is skipped by default. Start the candidate server with an empty temporary account database, administrator `synthetic-user` / `synthetic-password`, and outbound provider traffic blocked, then run:

```sh
BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE=1 \
  BRIDGE_VOICE_ACCEPTANCE_URL=http://127.0.0.1:18080 \
  uv run --python 3.12 --extra test pytest -q tests/test_voice_bridge_acceptance.py
```

The URL may include a deployment base path. The separate `DISPOSABLE=1` guard is required before requests are sent. This test writes and updates `bridge-acceptance@example.test`, uses synthetic credentials only, and leaves that record in the disposable store. Never point it at a production account store. It checks missing/wrong Basic authentication on all endpoints, absent-record 404, malformed/oversized requests, capabilities, direct and authenticated proxy readback, optional device ID, the UTF-8 digest, repeated synchronization, a lost PUT response, identity/token conflicts, idempotency-key replay, and reconciliation after remote credential changes. Same-key/different-body reuse must return 409. It never invokes native token-check or provider endpoints. The server's own tests must additionally verify transaction rollback, restart persistence, account-row uniqueness, digest recomputation after independent account changes, and actual transport proxy selection. This harness alone does not verify those storage or runtime properties and does not establish real-account usability.

## Verification

Run `uv run --python 3.12 --extra test pytest`. `tests/test_integrations.py` uses synthetic data and `httpx.MockTransport`, with no real credentials, browser state, logins, or external account traffic. Both public source inspection and mock verification are distinct from real-account acceptance. Real verification must be performed serially by the main agent.
