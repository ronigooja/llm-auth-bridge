# Voice integration

## Protocol and source

Voice targets must explicitly select `compatibility: "bridge-v1"` and supply
`base_url`, `admin_username`, and `admin_password`. Management uses HTTP Basic
without browser cookies. The server contract is `docs/BRIDGE_V1.md` in the
[pinned ronigooja fork](https://github.com/ronigooja/chatgpt-web-voice/tree/e6001bc98fabdfc2a8a14478ed426b90e1107c89).
[Source metadata](../../../deploy/voice/source.json) pins the fork revision and
release image. Refer to that contract for endpoints, body limits, canonical
encoding, idempotency, errors and persistence. The [fork build entry point](../../../deploy/voice/README.md)
covers installation; [deployment](../../guides/deployment.md) covers recovery.

Only the pinned fork revision is supported. Other public gateway revisions may
lack administrator CRUD or return masked route/token previews. Native CRUD or a
token probe cannot attest exact credentials and explicit routes. Unsupported
targets fail closed.
Current acceptance and remaining real-account checks live in the [roadmap](../../roadmap.md).

## Bridge responsibilities

The client checks capabilities before writing. It sends only `chatgpt_web`
access tokens and an optional nonempty `device_id`, excluding refresh tokens.
Current browser extraction supplies only the access token. The ID for a new
binding is `bridge-` followed by the first 32 hex characters of SHA-256 over UTF-8
`chatgpt-web-voice:<casefolded identity>`; an existing stored remote ID is reused.
The idempotency key binds that ID and the entire canonical PUT-body digest.
Readback instead hashes only the actual persisted credential object. Both use
sorted keys, compact UTF-8 JSON, unescaped non-ASCII characters and no newline.
Do not normalize credential strings or proxy URLs. Go's default escaping of
`<`, `>`, `&`, U+2028 and U+2029 is incompatible. A cross-language vector is:

```text
JSON representation: {"access_token":"synthetic","device_id":"测试<&>\u2028\u2029"}
SHA-256: 5fcc9d4ab814aedce4447a6dd1243d8f67353cf8270f4d23eeaef6aa6286502d
```

The displayed Unicode escapes represent literal separator characters in the
hashed bytes. An omitted device ID stays absent from the digest even when the
server runtime uses its global device default.

The bridge reconciles a lost PUT response against persisted identity, type,
credential digest and complete explicit route. Changed credentials/routes stop
reconciliation; fresh authorization may intentionally replace the same identity.
A preview or empty proxy cannot prove direct routing. The patched server must
bypass inherited proxies for explicit direct mode in every upstream transport;
explicit proxy mode must override process `NO_PROXY`. Management handlers must
never invoke provider login, token checks, refresh or sessions. Runtime transport
and Voice audio acceptance are separate from storage consistency.

## Disposable synthetic HTTP acceptance
[`tests/test_voice_bridge_acceptance.py`](../../../tests/test_voice_bridge_acceptance.py) exercises the real bridge client over HTTP against an independently started, disposable server. It is skipped by default. Start the candidate server with an empty temporary account database, administrator `synthetic-user` / `synthetic-password`, and outbound provider traffic blocked, then run:

```sh
BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE=1 \
  BRIDGE_VOICE_ACCEPTANCE_URL=http://127.0.0.1:18080 \
  uv run --python 3.12 --extra test pytest -q tests/test_voice_bridge_acceptance.py
```

The URL may include a deployment base path. The separate `DISPOSABLE=1` guard is required before requests are sent. This test writes and updates a unique `bridge-acceptance-<run ID>@example.test` account with unique synthetic tokens on every run, and leaves that record in the disposable store. Never point it at a production account store. It checks missing/wrong Basic authentication on all endpoints, absent-record 404, malformed/oversized requests, capabilities, direct and authenticated proxy readback, optional device ID, the UTF-8 digest, repeated synchronization, a lost PUT response, identity/token conflicts, idempotency-key replay, and reconciliation after remote credential changes. Same-key/different-body reuse must return 409. Historical-key replay must preserve newer persisted credentials and routes; a fresh replacement uses a new payload and key. It never invokes native token-check or provider endpoints. The server's own tests must additionally verify transaction rollback, restart persistence, account-row uniqueness, digest recomputation after independent account changes, and actual transport proxy selection. This harness alone does not verify those storage or runtime properties and does not establish real-account usability.
