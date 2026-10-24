# Voice bridge-v1 gateway fork

This overlay implements the bridge management API in the native Go gateway from
Space3044/chatgpt-web-voice at `6338ac478070aaa34bfe7a3c0469caf9e9174c02`.
The reviewed source delta is `bridge-v1.patch`; its checksum is recorded beside it.
The fork and all transports remain **unverified with real provider accounts**.
Synthetic management readback verifies stored configuration, not account usability
or the provider-observed egress IP.

## Build

Requirements: Git, SHA-256 utilities, a Go toolchain compatible with the pinned
upstream `go.mod` and Docker. Module dependencies are pinned by upstream `go.sum`.
Use the existing upstream runtime image built from the pinned revision, preferably
an immutable registry digest or a recorded local image ID. It supplies the existing
curl-impersonate runtime, static assets, CA bundle, nonroot user and environment.
The overlay replaces only `/app/server`.

```sh
./deploy/voice/build.sh /tmp/voice-bridge-build \
  'registry.example/voice@sha256:REPLACE_WITH_VERIFIED_RUNTIME_IMAGE_DIGEST' \
  llm-auth-bridge/voice:bridge-v1
```

The script creates a fresh output directory, checks the patch checksum, checks out
the exact upstream revision, applies the patch, runs all Go tests and builds a
static Linux server before constructing the overlay image. Set `GOARCH` explicitly
for cross builds; the runtime image architecture must match. A preexisting output
directory is rejected. Build output and cloned sources should stay outside Git.
For an offline rebuild, make the pinned Git commit and Go module cache available
locally and perform the same checkout, patch verification, tests and build steps.

For an already tested local source checkout, reuse its Go cache and build binary
with the same command above, then build this Dockerfile with a context containing
only `server` and `Dockerfile`; include the actual patch SHA-256 as the label arg.
Do not use the original upstream Dockerfile merely to replace an already available
runtime image: that downloads curl-impersonate and repeats unrelated layers.

## Management and persistence

The new endpoints require HTTP Basic credentials from `VOICE_AUTH_USERNAME` and
`VOICE_AUTH_PASSWORD`. Cookie sessions and downstream API keys do not authorize
these endpoints. Existing native administrator and downstream routes retain their
existing authentication behavior. Terminate TLS at the service or trusted reverse
proxy; plain HTTP is suitable only on an explicitly trusted private network.

- `GET /bridge/v1/capabilities` reports protocol, explicit routing and credential
  digest support.
- `PUT /bridge/v1/accounts/{remote_id}` atomically persists a native account and its
  durable bridge ID mapping. Supply a nonempty `Idempotency-Key` (at most 512 bytes).
  Reusing a key with a different canonical request returns 409. Replaying an old
  successful request reads current state and never replaces a newer native edit.
- `GET /bridge/v1/accounts/{remote_id}` reads the actual persisted native token,
  identity, route and optional device ID and computes the credential SHA-256.
  Absent mappings return 404; identity or duplicate token conflicts return 409.

Bodies are capped at 1 MiB; malformed requests and unknown fields return 400.
Only `chatgpt_web` access tokens and optional device IDs are accepted; refresh
tokens are rejected. Per-account device IDs override the global fingerprint on
provider requests; omission keeps the original global fallback. Explicit `direct`
routing bypasses environment proxies in Go, tls-client and curl transports; native
accounts with an empty route retain their legacy environment inheritance.

Tokens, proxy URLs (including authentication) and device IDs use the existing
`VOICE_TOKEN_ENCRYPTION_KEY` AES-GCM encryption at rest. Startup also seals legacy
plaintext proxy values without changing routing semantics. Keep this key and the
SQLite volume together in existing secret storage, outside source control.
Bridge tables are created automatically in the existing SQLite database. Back up
the database and key before changing the running image. Rolling back to an older
binary after bridge writes is not supported: old binaries cannot interpret sealed
proxy values or the direct sentinel. Restore the backup and previous image together
if a rollback is needed.

Keep the existing runtime volume, UID and network settings. Deploy serially,
confirm the Basic-auth capability endpoint, then use the bridge's synthetic
acceptance harness on a dedicated empty temporary database. Provider account
verification must be performed separately, serially by the main operator. Never
point the synthetic acceptance harness at a live populated deployment.
