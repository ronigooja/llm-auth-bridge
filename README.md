# LLM Auth Bridge

Single-administrator Linux console for account import, serial browser authorization,
human takeover, and typed credential synchronization to CLIProxyAPI and compatible
Voice gateways. Product screens are Chinese; execution events and project
documentation are English. Built with Python 3.12, FastAPI, SQLite, React,
Playwright, Camoufox, and Docker Compose.

## Start

Follow the [deployment guide](docs/guides/deployment.md) to provision a raw 32-byte
master key, initialize the administrator with `python -m app.cli init`, migrate an
existing installation offline, and start the app and worker. The default listener
is `127.0.0.1:8000`; use HTTPS and keep browser transport ports private.

The console provides separate ChatGPT and Codex login actions and an account
window backed by each account's persistent encrypted Camoufox/Firefox device. Codex uses
a Web-before-Codex task dependency. Follow the [account workflow](docs/guides/account-workflow.md)
for setup, manual challenges, takeover, and synchronization recovery.

Implementation, synthetic checks, and assisted real-account observations have
different acceptance boundaries. Consult the [capability matrix and remaining
acceptance](docs/roadmap.md) before relying on an integration.

## Documentation by reader

| Reader | Entry points |
| --- | --- |
| Operator | [Deployment and recovery](docs/guides/deployment.md), [account workflow](docs/guides/account-workflow.md), [troubleshooting](docs/troubleshooting/) |
| Contributor | [Development, tests and CI](docs/guides/development.md), [project working agreement](AGENTS.md) |
| System maintainer | [Architecture overview](docs/architecture/overview.md), [runtime and browser devices](docs/architecture/runtime.md), [data and tasks](docs/architecture/data-and-tasks.md), [security boundaries](docs/architecture/security.md) |
| API or adapter author | [HTTP API](docs/contracts/http-api.md), [worker/adapters](docs/contracts/worker-adapters.md), [account window transport](docs/contracts/account-window.md), [CLIProxyAPI](docs/contracts/integrations/cliproxyapi.md), [Voice](docs/contracts/integrations/voice.md) |
| Product/UI contributor | [Authentication behavior](docs/product/authentication.md), [UI guidelines](docs/product/ui-guidelines.md) |
| Acceptance reviewer | [Capabilities, evidence and open work](docs/roadmap.md) |

Architectural decisions are linked from the [architecture overview](docs/architecture/overview.md).
Configuration belongs in the deployment guide; test commands belong in the
development guide; current acceptance status belongs in the roadmap.
