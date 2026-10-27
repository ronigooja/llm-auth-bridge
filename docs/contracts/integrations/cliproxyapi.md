# CLIProxyAPI integration

## Protocol selection and source

New CLIProxyAPI targets default to `cpa-native-oauth-v1`. Existing saved protocols
are preserved; select `cpa-auth-files-v1` explicitly for a stock server. Explicit
null retains legacy auth-files behavior. There is no automatic protocol fallback.
See [acceptance status](../../roadmap.md) before enabling either path.

The native server's original contract is `docs/bridge-oauth-v8.md`, included in
[the pinned extension patch](https://github.com/ronigooja/llm-auth-bridge/blob/d22cdb8034f736aa4deca6a08de87dbc64f30435/deploy/cpa/upstream.patch#L7-L32).
[Source metadata](../../../deploy/cpa/source.json) pins the public upstream,
reviewed extension revision, and patch checksum. Use that contract for endpoint
fields, states, error codes, persistence, and native-store restrictions; the
[overlay build entry point](../../../deploy/cpa/README.md) explains rebuilding.

## Native OAuth bridge responsibilities

The target owns PKCE, code exchange, staging, and credential storage. The bridge
continues browser automation and human takeover through the explicit account
route, using management Bearer authentication under `/v8/management/bridge/oauth`.
Management traffic uses the separate transport defined in the
[adapter contract](../worker-adapters.md#downstream-transport).
The bridge never receives native provider tokens.

Before creating a remote session, the worker durably encrypts its session reference.
Before posting a callback, it durably records submission; a lost response is
reconciled by reading the session, never by replaying the code. Public task views,
UI and events exclude session IDs, authorization URLs, provider state and callback
codes. A staged credential is not installed or synchronized. Commit occurs only
after the worker's durable cancellation/write fence. A `committing` session needs
POST commit reconciliation; GET alone does not complete that operation.

The bridge accepts success only when actual persisted readback matches identity,
explicit route, stable remote ID, and the session's expected credential digest.
The digest is an opaque native token fingerprint, distinct from the Voice
credential-object digest. Readback does not prove asynchronous runtime reload,
provider usability or actual egress. Recovery and permissible target-secret repair
are defined in [data and tasks](../../architecture/data-and-tasks.md).

## Auth-files bridge contract
Configuration:

```json
{
  "base_url": "https://cpa.example.test",
  "management_key": "<management key>",
  "compatibility": "cpa-auth-files-v1"
}
```

New CPA targets created through the UI or API default to `cpa-native-oauth-v1` when the protocol is omitted. This auth-files contract is available by explicitly selecting `cpa-auth-files-v1`; legacy saved targets with absent or null protocols retain auth-files behavior. Explicit null in the API also retains that legacy behavior. Management requests use `Authorization: Bearer <management_key>`:

- Connection test: `GET /v0/management/auth-files`, requiring an object with a `files` array.
- Read/reconciliation: `GET /v0/management/auth-files/download?name=<remote_id>`; HTTP 404 means the named record does not exist.
- Create/update: `POST /v0/management/auth-files?name=<remote_id>` with raw JSON. The same filename overwrites that record.

Only browser results typed `codex_oauth` are accepted. The payload includes `type: codex`, `email`, `access_token`, `refresh_token`, `id_token`, `account_id`, optional RFC 3339 `expired`, and `proxy_url`. The browser must have completed its PKCE exchange through the account route. Direct accounts use the explicit `proxy_url: "direct"` sentinel; proxied accounts use a full validated proxy URL. Blank `proxy_url` would inherit the downstream global proxy and is never emitted or accepted as proof of direct routing.

New filenames are `bridge-<32-character identity/kind hash>.json`; usernames and credentials do not appear in newly generated filenames. If the local account/target pair has no stored remote ID, the worker first searches the CLIProxyAPI auth-files list for a unique `codex` file whose email matches the authenticated identity, then persists the selected existing filename (or the deterministic new filename) to the task before attempting a write. This allows first-time bridge synchronization to adopt a provider-generated legacy filename without creating a duplicate. An unavailable or incompatible listing and multiple identity matches stop before any write; multiple matches require manual reconciliation. Existing persisted filenames take priority and are reused after strict filename validation. A preexisting record with a different identity is never overwritten. Credential refreshes retain unrelated existing auth-file settings such as priority, weight, and disabled status. Downloaded JSON must match every emitted credential and route field before synchronization succeeds. On a subsequent worker attempt, the worker passes `result["_reconcile_only"] = true`: an existing mismatched credential or route then produces a safe pending conflict and is never overwritten, because the remote service may have rotated its refresh token after a lost response. An absent record can still be uploaded. A fresh browser authorization may intentionally replace an existing record for the same identity. After any write, a present but mismatched record immediately stops synchronization without a second write; a freshly rotated token must not be replaced by the old local token. This verifies stored configuration; it does not prove the downstream service's actual egress IP, runtime policy overrides, or account usability. Deployments must separately accept their downstream runtime behavior.

Public source reviewed on 2026-10-23: [router-for-me/CLIProxyAPI at d946c4f](https://github.com/router-for-me/CLIProxyAPI/tree/d946c4fba6fc9a5cfbca1f3d85184d62ad2fb683), particularly `internal/api/handlers/management/auth_files_crud.go`, `internal/auth/codex/token.go`, `internal/watcher/synthesizer/file.go`, `sdk/proxyutil/proxy.go`, and `internal/runtime/executor/helps/proxy_helpers.go`. These establish raw JSON upload/download, token storage fields, per-account `proxy_url`, and the explicit `direct` sentinel. Older or modified servers may differ; incompatible responses fail closed.
