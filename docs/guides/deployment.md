# Deployment

The Compose deployment runs one web app and one serial browser worker against a shared SQLite database and lock file. Keep one worker replica. Real provider login, downstream synchronization, and production egress remain **unverified**; consult [the roadmap](../roadmap.md) for capability status.

## Provision and start

Use Docker Engine with Compose v2. Create a dedicated 32-byte encryption key and administrator password outside version control:

```sh
mkdir -p .secrets && chmod 700 .secrets
openssl rand -out .secrets/master_key 32
chmod 600 .secrets/master_key
docker compose build
docker compose run --rm --no-deps app python -m app.cli init
docker compose up -d
```

Initialization prompts for the administrator password. For unattended provisioning, mount a temporary password file readable by UID/GID 10001 and pass `--password-file`; remove the mount immediately. Keep the key separate from database backups: losing it makes encrypted data unrecoverable.

Publish HTTPS through a reverse proxy to `127.0.0.1:8000`. Forward WebSocket upgrades for `/api/v1/tasks/*/takeover`, disable buffering for task SSE, and allow long SSE/WebSocket timeouts. Keep the app and `/novnc/` on one origin. Do not publish the worker's VNC or websockify ports. `LLM_AUTH_SECURE_COOKIE` defaults to `true`; set it to `false` only for loopback HTTP evaluation, then restore the secure default.

For a local HTTP installation, persist `LLM_AUTH_SECURE_COOKIE=false` in the ignored `.env` file and open `http://127.0.0.1:8000` after startup. A trusted LAN installation additionally sets `LLM_AUTH_BIND_HOST=0.0.0.0`; use HTTPS and secure cookies for any deployment beyond a trusted network.

Configure CLIProxyAPI targets with the service root URL (without `/v1`). The management key is separate from an inference key. A reachable endpoint or successful connection test does not verify management authorization or real-account behavior.

## Upgrade, backup, and restore

Before an upgrade, disable scheduled maintenance, wait for active work to finish, stop both services, and back up with the CLI to a directory writable by UID 10001:

```sh
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

The worker uses headed Chromium in a TigerVNC desktop with Openbox and dynamic dimensions. The browser follows desktop resize events; fixed-size Xvfb/x11vnc runtimes are incompatible with account-window resizing. VNC and websockify remain private to the Compose network. Temporary profiles, display sockets, and GOST configuration live on a private `/tmp` mount; containers run as UID/GID 10001.
