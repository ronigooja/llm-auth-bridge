# LLM Auth Bridge

Single-administrator Linux management console for account import, serial browser authorization, human takeover, and typed credential synchronization. Product screens are Chinese; execution events and documentation are English. Python 3.12, FastAPI, SQLite, React, Playwright, and Docker Compose.

## Start

Follow [deployment](docs/deployment.md) to build app/worker images, provision a **raw 32-byte** master key, initialize the administrator with `python -m app.cli init`, and start Compose. The default listener is `127.0.0.1:8000`; use HTTPS and keep the worker VNC/WebSocket ports private. Initialization and migrations run offline, never as service import side effects.

For local synthetic development:

```sh
uv sync --frozen --extra test --extra browser --python 3.12
cd frontend
npm ci
npm test
npm run build
cd ..
uv run pytest
```

Use `LLM_AUTH_DB` and `LLM_AUTH_MASTER_KEY_FILE` for storage locations. `LLM_AUTH_SECURE_COOKIE=false` permits local HTTP development; the production default is true. Never commit account files, secrets, databases, browser state, or sensitive screenshots.

Account login and verification-code request IDs use `crypto.getRandomValues`,
including on trusted LAN HTTP origins where `crypto.randomUUID` is unavailable.
This compatibility does not change the HTTPS recommendation or cookie settings.

## Capability and acceptance

| Capability | Implementation | Acceptance |
|---|---|---|
| Administrator sessions, CSRF, CRUD, import preview/atomic confirmation | Implemented | Synthetic tests passed |
| Explicit migration, encrypted secrets, backup/restore | Implemented | Synthetic tests passed |
| Serial worker, leases/fencing, recovery, human code, SSE, sync retry | Implemented | Synthetic tests passed |
| Chinese built UI and authenticated takeover tunnel | Implemented | Live synthetic HTTP/browser and WebSocket tests passed |
| OpenAI password/TOTP/OAuth/browser session adapter | Implemented | Synthetic tests passed; real provider unverified |
| HTTP/HTTPS/SOCKS5 GOST routing, no direct fallback | Implemented | ARM64 local synthetic proxy tests passed; real egress unverified |
| CLIProxyAPI native auth-files synchronization | Implemented | Mock contracts and deployed management connection passed; real account synchronization unverified |
| Voice `bridge-v1` compatibility client and session maintenance | Implemented client | Mock contracts passed; disposable real-HTTP acceptance harness supplied; server/deployment and real-account acceptance remain unverified |
| Native voice gateway administrator CRUD synchronization | Unsupported pending deployed contract | No compatible native contract verified |
| Automatic site-specific webmail retrieval | Freshness/security primitives only | No site adapter; use manual code/takeover |
| ARM64/amd64 containers and production Chromium sandbox | Build definitions/CI supplied | ARM64 images built and deployed; nonroot sandbox passed; amd64 runtime unverified |

This is an implemented and synthetically exercised bridge, **not full real-account product acceptance**. Read [verification and remaining work](docs/roadmap.md) before deployment. The reviewed public voice gateways require a server patch for the [compatibility contract](docs/integrations.md#server-implementation-requirements); connecting their native account CRUD API alone does not provide synchronization. The [disposable synthetic HTTP acceptance harness](docs/integrations.md#disposable-synthetic-http-acceptance) verifies a candidate patched deployment without provider traffic. No claim of generic automatic webmail support is made.

See [architecture](docs/architecture.md), [authentication](docs/authentication.md), [integrations](docs/integrations.md), [development](docs/development.md), and [UI guidelines](docs/ui-guidelines.md).
