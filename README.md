# LLM Auth Bridge

LLM Auth Bridge is a single-admin Linux service for browser-based OpenAI account authorization and credential synchronization. The first release provides a FastAPI foundation, encrypted SQLite secret storage, import validation, target configuration, and durable task records. Browser login, mailbox adapters, and downstream sync adapters are extension points and remain **unverified** until exercised against configured services.

## Quick start

```bash
mkdir -p .secrets
openssl rand -out .secrets/master_key 32
chmod 600 .secrets/master_key
docker compose up --build
```

The service binds to `127.0.0.1:8000`. Put it behind an existing HTTPS proxy or use an SSH tunnel. API routes are under `/api/v1`; `/docs` exposes the development OpenAPI page.

## Support matrix

| Area | Status |
|---|---|
| OpenAI account import and encrypted metadata | Implemented |
| CLIProxyAPI Codex OAuth | Contract planned; real integration unverified |
| chatgpt-web-voice token sync | Contract planned; real integration unverified |
| Browser worker, TOTP, web mailbox, takeover | Planned extension points |
| IMAP, multi-tenant, concurrent browsers | Out of scope for v1 |

See [architecture](docs/architecture.md), [authentication](docs/authentication.md), [integrations](docs/integrations.md), and [development](docs/development.md).

The interface rules are documented in [UI guidelines](docs/ui-guidelines.md).

