# Deployment

The Compose stack has a web app and one serial browser worker sharing SQLite and a browser lock. Keep one worker replica. Authentication and downstream synchronization remain **unverified with real accounts**. Image builds and supported CPU architectures must pass CI and deployment acceptance; the presence of a Dockerfile is not verification.

## Initialize

Use Docker Engine with Compose v2. The frontend build uses the committed npm lock; Python uses the committed uv lock. Playwright and its bundled Chromium revision are pinned by Playwright 1.56.0. The worker uses headed Chromium for login and human takeover; builds pass `--no-shell` to skip the unused separate Headless Shell download. The worker includes GOST 3.3.1, with release SHA-256 checksums embedded for amd64 and arm64. These build paths are not architecture acceptance results.

Create a dedicated encryption key and administrator password file outside version control:

```sh
mkdir -p .secrets
chmod 700 .secrets
openssl rand -out .secrets/master_key 32
chmod 600 .secrets/master_key
# Create .secrets/admin_password with a password manager or a local editor.
docker compose build
```

The app runs as UID/GID 10001. Ensure the Compose secret can be read by that UID (a host secret mount may preserve its host permissions):

```sh
sudo chown 10001:10001 .secrets/master_key
```

Initialize before starting services. This command asks for the administrator password interactively, without putting it in shell arguments or history:

```sh
docker compose run --rm --no-deps app python -m app.cli init
```

For noninteractive initialization, mount a temporary password file readable by UID 10001 and run `python -m app.cli init --password-file /run/admin_password`; remove the mount immediately afterward. Never commit either file. Keep the encryption key separately from database backups; loss of the key makes stored secrets unrecoverable.

```sh
docker compose up -d
```

Publish HTTPS through a reverse proxy to `127.0.0.1:8000`. Forward WebSocket upgrades for `/api/v1/tasks/*/takeover`, disable response buffering for task SSE, and allow long SSE/WebSocket timeouts. Keep the web app and `/novnc/` on the same origin. The worker's port 6080 must stay private to the Compose network: never publish VNC or websockify directly.

`LLM_AUTH_SECURE_COOKIE` defaults to `true`. For a local-only HTTP evaluation, set `LLM_AUTH_SECURE_COOKIE=false` in the invoking environment. Restore `true` before HTTPS deployment.

## Local HTTP installation

For a loopback-only installation, persist the cookie setting in the ignored `.env` file:

```sh
printf 'LLM_AUTH_SECURE_COOKIE=false\n' > .env
chmod 600 .env
```

Open `http://127.0.0.1:8000` after initialization and startup. The login form takes only the administrator password. If a generated bootstrap password was saved to `.secrets/admin_password`, read it locally and change it in Settings after signing in. Keep this file private and outside Git.

To initialize using that file without retaining a password mount on either service:

```sh
docker compose run --rm --no-deps \
  -v "$PWD/.secrets/admin_password:/run/admin_password:ro" \
  app python -m app.cli init --password-file /run/admin_password
docker compose up -d --wait
docker compose ps
```

The password file must be readable by UID 10001. Run initialization only for a new database. The named `app-data` volume persists the database across container replacement; do not remove it during routine restarts. Both services use `restart: unless-stopped`.

Configure a CLIProxyAPI target with the service root URL, without the inference `/v1` suffix. Its management key is separate from an inference API key. A `401` response from `/v0/management/auth-files` proves the endpoint is reachable but does not validate management access. No real-account verification is implied by a healthy local stack.

## Trusted LAN access

The default published address is loopback. To reach the console from another device through `http://debian.local:8000`, set `LLM_AUTH_BIND_HOST=0.0.0.0` in the ignored `.env` file and recreate the app:

```sh
docker compose up -d --no-build --no-deps app
```

For HTTP, retain `LLM_AUTH_SECURE_COOKIE=false`. This exposes port 8000 on host IPv4 interfaces; use it on a trusted LAN. The client must resolve `debian.local` to the host LAN address; otherwise use the numeric LAN address. The worker VNC port remains private. For HTTPS deployment, restore secure cookies and use the reverse proxy configuration above.

## Operations

Use the Settings screen to inspect worker/browser availability, enable maintenance mode, set retention, and change the administrator password. Task progress reconnects using SSE. Takeover uses the app's authenticated WebSocket proxy and the bundled noVNC client. Browser tracing, HAR, and video are not enabled.

Before upgrading, disable scheduled maintenance, wait for active work to finish, and stop both services. Back up the database with the CLI to a mounted directory writable by UID 10001:

```sh
mkdir -p backups
sudo chown 10001:10001 backups
docker compose stop
docker compose run --rm --no-deps -v "$PWD/backups:/backups" app python -m app.cli backup /backups/bridge.sqlite3
docker compose build
docker compose run --rm --no-deps app python -m app.cli migrate
docker compose up -d
```

To restore, stop both services first. The destination must be absent. Preserve the current database and its sidecars in a separate directory before restoration:

```sh
docker compose run --rm --no-deps app sh -c 'mkdir /data/pre-restore && mv /data/app.sqlite3* /data/pre-restore/'
docker compose run --rm --no-deps -v "$PWD/backups:/backups:ro" app python -m app.cli restore /backups/bridge.sqlite3
docker compose up -d
```

Restore the matching encryption key separately. Treat backups as sensitive even though credential fields are encrypted. Test backup and restore with synthetic data before relying on the procedure.

## Target compatibility

CLIProxyAPI uses `cpa-auth-files-v1`. ChatGPT Web Voice automatic synchronization requires an explicitly selected `bridge-v1` compatible service. A connection test proves reachability only; it does not verify real-account login, credential acceptance, or proxy behavior. Keep capabilities marked unverified until serial real-account acceptance passes.

## Local frontend verification

```sh
cd frontend
npm ci
npm test
npm run build
```

The backend serves `frontend/dist`; `npm run dev` is intended for UI development with an explicitly configured same-origin API proxy. Do not expose the Vite server as a production deployment.

For the original unversioned scaffold database, retain its original 32-byte key and run `init` once to migrate and register the administrator. Later upgrades use `migrate`. Never generate a replacement key for an existing encrypted database. Initialization refuses that case. Restore archives must use a fresh destination directory; choose a new archive name if `/data/pre-restore` already exists.

The worker mounts `/tmp` as a private tmpfs for temporary profiles, GOST configuration and display sockets, with 1 GiB shared memory. Both services run as UID 10001 without published VNC ports. Compose health checks test app readiness and recent worker heartbeat; worker shutdown has a sixty-second grace period. Browser sandbox success must still be verified on the deployment host. `/readyz` is a database/key readiness check; it does not attest provider or downstream availability.

Backup archives are normalized to SQLite DELETE journal mode so a single archive can be mounted read-only. Restore re-enables WAL on the new writable database. The backup/restore tests include an unprivileged reader of a read-only archive directory.

The worker uses the [Playwright 1.56.0 seccomp profile](https://github.com/microsoft/playwright/blob/v1.56.0/utils/docker/seccomp_profile.json), vendored at `deploy/playwright-seccomp.json`. It permits the `clone`, `setns`, and `unshare` calls needed by Chromium user namespaces while retaining a default-deny syscall policy. The app retains Docker default seccomp restrictions. Chromium sandboxing stays enabled; no privileged mode or `SYS_ADMIN` capability is required.

## Voice gateway on the external cylo network

For a separately deployed voice gateway attached to the existing Docker network `cylo`, add `COMPOSE_FILE=docker-compose.yml:deploy/voice-network.compose.yml` to the ignored `.env` file and recreate app/worker with `docker compose up -d --no-build`. Both bridge services retain their default network and also join `cylo`. The network must already exist. No gateway ports need to be exposed to the LAN.

From bridge containers, the native gateway root is `http://cylo-voice-gateway:8090`, not host loopback `http://127.0.0.1:18090/login`. The `/login` suffix is a browser page, not an integration base URL. Target HTTP access requires explicit `allow_http: true`.

Space3044 commit `6338ac478070aaa34bfe7a3c0469caf9e9174c02` does not implement `bridge-v1`. Shared networking alone does not enable synchronization. A compatible server implementation must be supplied and verified before adding a voice target; do not label the native gateway as compatible merely because its login page or account list works. See the [integration contract](integrations.md#chatgpt-web-voice-compatibility-api).

Before deploying a patched gateway against existing accounts, run the [disposable HTTP acceptance harness](integrations.md#disposable-synthetic-http-acceptance) against a separate instance with a fresh temporary database and fixed synthetic administrator credentials. Both the endpoint URL and `BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE=1` must be set explicitly. Block outbound provider traffic for that instance. The harness changes a synthetic account and must never run against the production database. Verify restart persistence, actual account-store readback, direct routing despite process proxy variables, and per-account device headers through the server's own tests as well. Keep real-account usability unverified until the main agent completes serial acceptance using credentials outside Git.
