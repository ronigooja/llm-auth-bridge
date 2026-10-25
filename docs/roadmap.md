# Verification and remaining work

## Current implementation

The authenticated Chinese console, offline initialization/versioned migration, encrypted CRUD/import, global serial queue, fencing/leases/recovery, manual inputs/takeover tunnel, OpenAI browser/OAuth/session adapter, GOST account routes, CPA auth-files client, opt-in native CPA OAuth extension client, stable encrypted per-account browser identity/session reuse, voice compatibility client, session maintenance, pending-sync recovery, backup/restore, multi-stage build definitions and CI are implemented.

Synthetic acceptance on the ARM64 host uses Python 3.12, real local HTTP/WebSocket services, system Chromium and checksum-checked GOST 3.3.1. Frontend interaction tests and production build pass. Test-only root Chromium is unsandboxed; a separate ARM64 Compose acceptance check passed with headed Chromium sandboxing enabled as UID 10001. See development for prerequisites and coverage, and the final delivery record below.

Native CPA authorization and stable browser identities are new implementation paths pending integrated CI and deployed acceptance. Native authorization requires the patched target extension and remains opt-in; existing auth-files targets retain their protocol. Browser identities use supported native context settings and do not guarantee complete fingerprint isolation.

## Required before full product acceptance

- Deploy and synthetically accept the patched native CPA extension before enabling `cpa-native-oauth-v1`; verify staging/commit recovery, route use and token ownership. Complete serial real-account native authorization and Voice/Codex saved-session reuse acceptance. These remain unverified.
- Supply a serially usable test account and deployed CPA/voice configurations securely outside Git. No real-account login, TOTP/email branch, downstream usability or voice session has been verified.
- Complete serial real-account acceptance for the deployed voice `bridge-v1` overlay; authenticated management and the configured bridge target connection test have passed. The reviewed fork and isolated synthetic HTTP acceptance now pass; the ARM64 native gateway has been replaced with the patched image while preserving its existing runtime configuration. Synthetic persistence, credential digest, explicit route readback and unauthenticated rejection do not establish provider usability or actual account egress. Native voice synchronization remains unverified with real accounts.
- Supply the actual mailbox site. Implement and accept its isolated list/detail reader, pre-request baseline, bounded polling, redirect/egress protection and fresh-message matching. Current code provides only conservative primitives and manual provider challenges.
- Build and run amd64 containers before claiming amd64 architecture acceptance. ARM64 app/worker builds, health checks, nonroot headed Chromium sandbox, private VNC/WebSocket transport and authenticated noVNC assets passed local deployment checks. Full real-provider remote desktop takeover remains unverified; the authenticated binary WebSocket tunnel is synthetically tested.
- Confirm real provider selectors, proxy egress and failure behavior, CPA identity/proxy/live account usability, voice token renewal/expiry/actual voice session, restart, and production backup/restore using the matching key.

Until these pass, advertise implementation/synthetic verification separately from **unverified** real integrations. No evidence in this delivery permits marking the full product accepted.

## Later versions

Other vendors, IMAP, concurrent browser scheduling, multi-user authorization, multi-host queues and automated CAPTCHA handling are outside v1 scope.

## Delivery verification record (2026-10-23)

- ARM64 native host, Python 3.12.14: 144 pytest cases passed, including local Chromium UI acceptance, authenticated binary WebSocket revocation, and real GOST HTTP/HTTPS/SOCKS5 fixture proxies. No real-account tests ran.
- Frontend: eight interaction tests, type check and production build passed; npm audit reported zero vulnerabilities at installation.
- Compose configuration and Git whitespace checks passed.
- Docker app build failed before image steps because registry-1.docker.io HEAD timed out while resolving docker/dockerfile:1.7. Worker/multiarchitecture images and nonroot sandbox remain unverified.
- Independent review covered auth, migration, fencing, cancellation and downstream uncertainty; its concrete findings were fixed and covered by regression tests.

## Local deployment verification record (2026-10-24)

- ARM64 app and worker images built and started through Docker Compose, running as UID 10001 with persistent SQLite storage and `unless-stopped` restart policies. The app publishes only `127.0.0.1:8000`; the worker publishes no host ports.
- Both container health checks passed. Local HTTP administrator login, built UI target display/logout, readiness, unauthenticated API rejection, worker heartbeat, and authenticated noVNC asset delivery passed.
- Headed Chromium launched with `chromium_sandbox=True` under the vendored Playwright seccomp profile. Private VNC and app-to-worker WebSocket/RFB handshakes passed.
- A deployed CLIProxyAPI management connection returned HTTP 200 using its dedicated management key, saved encrypted in the bridge database. No remote credential files were written and no real provider logins ran.
- All 144 pytest cases passed using the worker image's checksum-verified GOST binary; eight frontend interaction tests and the production frontend build passed.
- The initial images include Playwright's default Headless Shell download. Subsequent builds use `--no-shell` to omit that unused artifact; option support was checked against Playwright 1.56.0. The optimized image build has not been repeated.
- Real-account authorization/synchronization, voice compatibility, amd64 runtime and full provider takeover remain unverified.

## Voice overlay deployment record (2026-10-24)

- Reviewed upstream fork `32d696a` passed `go test ./...`; its exact upstream diff matches the checksum-pinned patch in `deploy/voice`. The disposable synthetic HTTP harness passed twice against a separate fresh-data gateway on loopback port 18991, without production account writes or provider access.
- The COPY-only ARM64 overlay was built from the immutable original native runtime. Its patch label, static Linux ARM64 binary metadata, and installed binary SHA-256 were verified. The deployed image is `llm-auth-bridge/voice:bridge-v1-32d696a`, pinned in the durable operational override to `sha256:525104f25a8d475a504d09449139b2887ecf285105b0183192081657fb3f15f3`.
- The native `cylo-voice-gateway` replacement preserves the original environment file, data mount, encryption key, `voice:voice` identity, hardening, `cylo` network, and existing loopback/LAN port bindings. A stopped-service SQLite API backup and matched database/image rollback instructions are stored privately outside Git; see deployment documentation.
- Live `/login` returned 200; unauthenticated bridge capabilities and account GET/PUT returned 401. Gateway, app and worker health checks passed after replacement. The main operator verified authenticated capabilities (HTTP 200 with `bridge-v1`, explicit-route and credential-digest support), configured encrypted local voice target ID 2, and passed its connection test (HTTP 200). Worker-side internal DNS/network access returned the expected unauthenticated 401. Real-account synchronization, provider egress, renewal and voice sessions remain **unverified**.
- Deployment worktree verification: `pytest -q` passed 141 tests with five expected opt-in/environment-dependent skips; `git diff --check` passed. The separately audited disposable HTTP acceptance passed twice before deployment.
