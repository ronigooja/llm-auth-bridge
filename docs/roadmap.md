# Verification and remaining work

## Current implementation

The authenticated Chinese console, offline initialization/versioned migration, encrypted CRUD/import, global serial queue, fencing/leases/recovery, manual inputs/takeover tunnel, OpenAI browser/OAuth/session adapter, GOST account routes, CPA auth-files client, voice compatibility client, session maintenance, pending-sync recovery, backup/restore, multi-stage build definitions and CI are implemented.

Synthetic acceptance on the ARM64 host uses Python 3.12, real local HTTP/WebSocket services, system Chromium and checksum-checked GOST 3.3.1. Frontend interaction tests and production build pass. Test-only root Chromium is unsandboxed; this does not verify the production sandbox. See development for prerequisites and coverage, and the final delivery record below.

## Required before full product acceptance

- Supply a serially usable test account and deployed CPA/voice configurations securely outside Git. No real-account login, TOTP/email branch, downstream usability or voice session has been verified.
- Select the actual voice gateway and implement/accept its administrator login, Cookie/CSRF, account CRUD/check and explicit route semantics. Public upstreams reviewed lack sufficient exact route/readback support. The supplied `bridge-v1` HTTP client requires a separately implemented compatibility layer; that layer is not included. Native voice synchronization is not complete.
- Supply the actual mailbox site. Implement and accept its isolated list/detail reader, pre-request baseline, bounded polling, redirect/egress protection and fresh-message matching. Current code provides only conservative primitives and manual provider challenges.
- Build/run the app and worker containers on ARM64; build amd64 and run it before architecture verification. Local Docker build was blocked at Docker Hub registry HEAD by network timeout, before image steps. Nonroot Chromium sandbox, Xvfb/x11vnc/noVNC runtime and a full remote desktop takeover remain unverified; the authenticated binary WebSocket tunnel is synthetically tested.
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
