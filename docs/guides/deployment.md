# Deployment

The Compose deployment runs one web app and one serial browser worker against a shared SQLite database and lock file. Keep one worker replica. Consult [the roadmap](../roadmap.md) for capability status and the limits of assisted account observations.

## Provision and start

Use Docker Engine with Compose v2. Create a dedicated 32-byte encryption key and administrator password outside version control:

```sh
mkdir -p .secrets && chmod 700 .secrets
openssl rand -out .secrets/master_key 32
chmod 600 .secrets/master_key
sudo chown 10001:10001 .secrets/master_key
docker compose build
docker compose run --rm --no-deps app python -m app.cli init
docker compose up -d
```

The secret mount must be readable by UID 10001; host bind mounts may retain host ownership and permissions. Run initialization only for a new database. Initialization prompts for the administrator password. For unattended provisioning, mount a temporary password file readable by UID/GID 10001 and pass `--password-file`; remove the mount immediately. Keep the key separate from database backups: losing it makes encrypted data unrecoverable.

Publish HTTPS through a reverse proxy to `127.0.0.1:8000`. Forward WebSocket upgrades for `/api/v1/tasks/*/monitor` and `/api/v1/tasks/*/takeover`, disable buffering for task SSE, and allow long SSE/WebSocket timeouts. Keep the app and `/novnc/` on one origin. Do not publish the worker's VNC or websockify ports. `LLM_AUTH_SECURE_COOKIE` defaults to `true`; set it to `false` only for loopback HTTP evaluation, then restore the secure default.

For a local HTTP installation, persist `LLM_AUTH_SECURE_COOKIE=false` in the ignored `.env` file and open `http://127.0.0.1:8000` after startup. A trusted LAN installation additionally sets `LLM_AUTH_BIND_HOST=0.0.0.0`; use HTTPS and secure cookies for any deployment beyond a trusted network.

Configure CLIProxyAPI targets with the service root URL (without `/v1`). The management key is separate from an inference key. A 401 response proves reachability only. A successful authenticated connection test verifies the management surface, while provider usability still requires separate acceptance.

## Upgrade, backup, and restore

Before an upgrade, disable scheduled maintenance, wait for active work to finish, stop both services, and back up with the CLI to a directory writable by UID 10001:

```sh
mkdir -p backups
sudo chown 10001:10001 backups
docker compose stop
docker compose run --rm --no-deps -v "$PWD/backups:/backups" \
  app python -m app.cli backup /backups/bridge.sqlite3
docker compose build
docker compose run --rm --no-deps app python -m app.cli migrate
docker compose up -d
```

Schema v4 is the current schema. Migration is explicit and offline; app and worker must be stopped, and the existing encryption key must be used. Do not generate a replacement key for an existing database. Deploy app, worker, and frontend together.

To restore, stop both services and preserve the current database and sidecars before restoring into an absent destination:

```sh
docker compose run --rm --no-deps app sh -c 'mkdir /data/pre-restore && mv /data/app.sqlite3* /data/pre-restore/'
docker compose run --rm --no-deps -v "$PWD/backups:/backups:ro" app \
  python -m app.cli restore /backups/bridge.sqlite3
docker compose up -d
```

Offline restore accepts initialized v1–v3 archives and current-version archives, verifies the matching key, and migrates only the restored copy. The archive is unchanged; unsupported versions are rejected. A failed restore removes an incomplete destination, so retain the preserved database until success. Test backup and restore with synthetic data before relying on the procedure.

## Target compatibility

New CLIProxyAPI targets default to `cpa-native-oauth-v1`, which requires the reviewed management extension and its authenticated capability test. Existing targets retain their saved protocol, including legacy absent/null protocols that use auth-files; select `cpa-auth-files-v1` explicitly for stock servers. Native mode has no silent fallback. ChatGPT Web Voice synchronization requires an explicitly selected `bridge-v1` compatible service. See [CLIProxyAPI](../contracts/integrations/cliproxyapi.md) and [Voice](../contracts/integrations/voice.md).

## Runtime constraints

The worker uses headed Camoufox/Firefox in a TigerVNC desktop with Openbox and dynamic dimensions. The browser follows desktop resize events; fixed-size Xvfb/x11vnc runtimes are incompatible with account-window resizing. VNC and websockify remain private to the Compose network. Temporary profiles, display sockets, and GOST configuration live on a private `/tmp` mount; containers run as UID/GID 10001.


The worker uses the vendored [Playwright seccomp profile](../../deploy/playwright-seccomp.json)
from [Playwright 1.56.0](https://github.com/microsoft/playwright/blob/v1.56.0/utils/docker/seccomp_profile.json)
for Chromium user namespaces. Keep sandboxing, `no-new-privileges`, the private
tmpfs, shared memory and shutdown grace period from [Compose](../../docker-compose.yml).
Do not substitute privileged mode or disable the sandbox to work around host
configuration. Verify the sandbox on the deployment host. `/readyz` checks the
database/key; it does not attest provider or downstream availability. The named
`app-data` volume must survive routine container replacement.

## Voice overlay and recovery

Build the compatible gateway through [deploy/voice](../../deploy/voice/README.md).
Before upgrading an existing gateway, stop it and create a consistent SQLite
backup; preserve its encryption key, previous image and runtime configuration
outside Git. Keep the data mount, runtime UID, network and hardening settings.
Startup seals legacy proxy values, and explicit direct routing uses a sentinel
that older binaries do not understand. **Rollback requires restoring the matching
pre-upgrade database and previous image together**, with the same key. Preserve
the post-upgrade database and sidecars before restoring; never overwrite a live
database. A binary-only rollback is unsafe.

For a separately managed gateway on the existing `cylo` network, the optional
[network overlay](../../deploy/voice-network.compose.yml) joins the bridge to that
network without publishing gateway ports. Persist
`COMPOSE_FILE=docker-compose.yml:deploy/voice-network.compose.yml` in the ignored
`.env` and retain it for later operations. The network must already exist. A
container service URL such as `http://cylo-voice-gateway:8090` is distinct from
host loopback and has no `/login` suffix; trusted HTTP requires `allow_http: true`.
Do not recreate the independently managed gateway during bridge upgrades.

Run the [disposable acceptance harness](../contracts/integrations/voice.md#disposable-synthetic-http-acceptance)
against a separate empty database with provider egress blocked before changing
production. Keep its synthetic credentials and account writes away from live data.

## Source-only worker fallback

The [source-only recipe](../../deploy/worker-source-update.Dockerfile) is usable
only with its exact previously verified runtime base. Before using it, compare
`pyproject.toml`, `uv.lock`, the standard Dockerfile, worker entrypoint, seccomp and
Compose settings with the base revision. If dependencies or runtime configuration
changed, rebuild the standard worker instead. Verify the exact local base image
against the recipe's pinned digest; a mutable alias alone is insufficient. This
recipe inherits the old runtime, so it cannot upgrade an Xvfb/x11vnc worker to the
current TigerVNC/Openbox stack. Do not use it as a current desktop upgrade path.

For any authorized image replacement, wait for active tasks to finish, disable
scheduled maintenance, retain rollback images, and use the existing Compose
configuration, key, volumes and networks. Restore the previous maintenance setting
after checking health, worker availability, source revision labels and served
frontend/viewer assets. Restarting a worker closes its browser and may require a
fresh authorization. Image integrity checks do not establish real-account acceptance.
