# Architecture overview

The bridge coordinates account authorization and verified credential handoff to
external services. It owns administrator access, account configuration, a serial
browser queue and durable recovery. Provider authentication remains a website
interaction; downstream services own credentials after verified handoff.

## Components and ownership

| Component | Responsibility | Implementation |
| --- | --- | --- |
| HTTP application | Administrator sessions, account/target management, task commands, event history and browser transport authorization | [main.py](../../app/main.py) |
| React frontend and account viewer | Task workflow, live progress and authenticated access to the current account browser | [frontend](../../frontend/), [account-viewer.js](../../app/static/account-viewer.js) |
| Worker | Queue ownership, browser lifecycle, human waits, credential synchronization and maintenance | [worker.py](../../app/worker.py), [queue.py](../../app/queue.py) |
| Browser runtime | Account device restoration, routed Camoufox/Firefox, provider interaction and private remote desktop | [browser.py](../../app/browser.py), [Dockerfile](../../Dockerfile) |
| Integration adapters | Downstream capability checks, writes, readback and reconciliation | [integrations.py](../../app/integrations.py), [cpa_oauth.py](../../app/cpa_oauth.py) |
| SQLite and mounted key | Durable state and encrypted material shared by app and worker | [db.py](../../app/db.py), [crypto.py](../../app/crypto.py) |

The application and one persistent worker run on one host, share the same SQLite
volume and process lock, and communicate with the browser through private
websockify transport. Independent locks on multiple hosts and network filesystem
deployments are unsupported. Compose publishes the app port only. The worker
owns Camoufox/Firefox and the desktop; the application never launches a second browser
for monitoring or takeover.

`create_app(Settings)` constructs the HTTP application without initializing keys
or migrating data. Startup validates the existing schema and encrypted key check.
Explicit CLI initialization and offline migration keep destructive setup separate
from serving requests; see the [deployment guide](../guides/deployment.md).

## Read by concern

- [Runtime and account identity](runtime.md) describes process topology, dynamic
  desktop geometry, persistent devices and platform emulation limits.
- [Data and task lifecycle](data-and-tasks.md) describes schema ownership,
  execution fencing, cancellation, recovery and retention.
- [Security boundaries](security.md) describes administrator access, secret
  storage, network routes and the live desktop trust boundary.
- Architecture decisions are indexed in the [ADR index](decisions/README.md).
- Operational incidents and phase-by-phase diagnosis belong in
  [troubleshooting](../troubleshooting/), including the
  [login authentication guide](../troubleshooting/login-auth.md). This section
  records observed failures and operator investigation steps; it does not
  redefine runtime or API contracts.

Interface details have one home: [HTTP API](../contracts/http-api.md),
[worker adapters](../contracts/worker-adapters.md) and
[account window transport](../contracts/account-window.md). Downstream protocol
requirements belong to [CLIProxyAPI](../contracts/integrations/cliproxyapi.md) and
[Voice](../contracts/integrations/voice.md). The [capability matrix](../roadmap.md) is the
authority for tested behavior, acceptance gaps and future work; the architectural
boundaries here do not establish real-account acceptance.
