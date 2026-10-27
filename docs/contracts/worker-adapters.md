# Worker and adapter contracts

Source interfaces: [worker control](../../app/worker.py),
[browser adapter](../../app/browser.py), [integrations](../../app/integrations.py),
and [native OAuth client](../../app/cpa_oauth.py). Task ownership and persistence
are defined in [data and tasks](../architecture/data-and-tasks.md).

## Browser adapter

`run_login(account, target, control, saved_state=None) -> dict` receives decrypted
account credentials, mailbox preference, explicit route/proxy, and browser profile;
target includes `kind` and `config`. `run_browser_window(account, control,
saved_state=None)` opens a target-free device and returns without extracting or
synchronizing credentials.

Control provides `phase(name, message)`, `checkpoint()`,
`wait_human(reason, *, phase="waiting_human") -> str | None`, `save_state(dict)`,
`load_device() -> bytes | None`, `save_device(bytes)`, `update_timezone(iana_id)`,
`browser_ready(port=6080)`, and `browser_closed()`. Native authorization also uses
`native_session()` and `native_callback_submitted()` for durable private references.
Checkpoints enforce cancellation, lease ownership, shutdown, deadlines and takeover.
Device methods bind archives to the leased account. After browser close,
`save_device` may preserve progress on cancellation while the lease is owned;
it cannot authorize more provider work or an expired owner's write.

Ordinary browser results contain `credential_type: "codex_oauth" | "chatgpt_web"`,
`credential`, `expires_at`, and `identity`. Native results contain `native_oauth:
{protocol, session_id}`, `remote_id`, `credential_type: "codex_oauth"`, and
`identity`, without provider tokens. Blocking synchronous Playwright runs under
the worker's global browser lock. Exceptions and phase messages must be fixed,
safe text without credentials or raw provider responses.

## Downstream adapter

`sync_credential(target, result, account, remote_id=None, *, _transport=None,
_sleep=time.sleep, _on_remote_id=None, _checkpoint=None) -> dict` returns
`{remote_id, verified: true}` only after readback of identity, credential contents
or digest, and explicit route. Here `verified` means storage consistency, not
provider usability. `test_connection(target) -> {reachable, verification:
"unverified"}` checks management reachability only. Native commits use
`NativeOAuth.commit(on_remote_id=None, checkpoint=None)` with the same readback
boundary. Protocol-specific requirements are in [CLIProxyAPI](integrations/cliproxyapi.md)
and [Voice](integrations/voice.md).

The worker encrypts pending results, tears down the browser before sync retry,
and deletes its active pending credential after handoff. A first-write callback
persists the selected remote ID before any upload. `IntegrationError.write_possible`
is false for fresh preflight failures and true once a write may have started.
On `_reconcile_only: true`, every failure retains prior write uncertainty,
including configuration/connection failures. Unknown exception types also retain
uncertainty. Auth-files and Voice synchronization never perform provider login,
code exchange, token refresh or live account probes. CPA owns refresh rotation.

## Downstream transport
All targets require `base_url`. HTTPS is required unless `allow_http: true` explicitly permits HTTP in a trusted deployment. URLs must not contain user information, query parameters, or fragments. A base path is supported. HTTP requests use a separate client with `trust_env=False`, TLS verification, redirects disabled, a five-second connection timeout, and a fifteen-second operation timeout. The account proxy is serialized into the remote account; it is never used to access the target management API. Targets need independent network reachability from the bridge worker.

GET requests have at most three attempts for transient transport errors, HTTP 429, 502, 503, and 504. Numeric `Retry-After` values above two seconds fail with a retry-later message; smaller values use a bounded delay. Long or date-form delays do not block the worker. Writes use a stable ID and are followed by readback even after a lost response. No unbounded retry loop is used. Remote bodies, URLs containing secrets, HTTP exception text, and credentials are not included in adapter errors or logs.

An account must declare `route_type: direct` or `route_type: proxy`. An absent proxy is never interpreted as direct. Proxy configuration uses `{server, username?, password?}`, with server schemes `http`, `https`, `socks5`, or `socks5h`; proxy credentials are URL encoded for downstream serialization.

The public account input accepts proxy schemes `http`, `https`, and `socks5`;
the downstream serializer additionally understands legacy/internal `socks5h`.
