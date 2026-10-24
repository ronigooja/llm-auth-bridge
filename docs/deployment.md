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

Unpatched Space3044 commit `6338ac478070aaa34bfe7a3c0469caf9e9174c02` does not implement `bridge-v1`. The reviewed overlay in `deploy/voice` adds that contract; its ARM64 deployment and synthetic acceptance are recorded below. A healthy login page alone does not establish compatibility or real-account usability. See the [integration contract](integrations.md#chatgpt-web-voice-compatibility-api).

Before deploying a patched gateway against existing accounts, run the [disposable HTTP acceptance harness](integrations.md#disposable-synthetic-http-acceptance) against a separate instance with a fresh temporary database and fixed synthetic administrator credentials. Both the endpoint URL and `BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE=1` must be set explicitly. Block outbound provider traffic for that instance. The harness changes a synthetic account and must never run against the production database. Verify restart persistence, actual account-store readback, direct routing despite process proxy variables, and per-account device headers through the server's own tests as well. Keep real-account usability unverified until the main agent completes serial acceptance using credentials outside Git.

## Deployed voice bridge overlay (2026-10-24)

The native ARM64 gateway now runs the reviewed `bridge-v1` overlay from fork revision `32d696af33f9d40dbb78402d429af316d9212a8f`. The fork diff against upstream exactly matches `deploy/voice/bridge-v1.patch` (SHA-256 `23b0d17b05c20ca36488774b2c19927cd41d251f78e0cc64502c28cb757440e0`). The COPY-only Dockerfile preserves the original runtime image `sha256:209392ce7c4994b70334ef53aa81adebba904ab01dc1bb3ae8d0b0dd0601bd7a`, including its runtime identity and curl-impersonate. BuildKit resolved that exact image through a verified local alias because a raw image ID in `FROM` is parsed as a repository reference.

Deployed image tag: `llm-auth-bridge/voice:bridge-v1-32d696a`. Its local immutable image ID is `sha256:525104f25a8d475a504d09449139b2887ecf285105b0183192081657fb3f15f3`; the patch label was verified. The installed `/app/server` SHA-256 is `ba4d9e8099ebf3ec25f7962f38b0f6f6a604b942acc68ae2452acab73f87305f`, matching the reviewed synthetic-server binary (`CGO_ENABLED=0`, Linux ARM64, Go 1.26.2).

The durable `/etc/cylo/voice.bridge.compose.yaml` contains only the image override, pinned to that immutable ID. Retain the existing base and LAN overrides when operating the gateway:

```sh
VOICE_LAN_BIND=192.168.1.4 docker compose -p cylo-voice \
  -f /etc/cylo/voice.compose.yaml \
  -f /etc/cylo/voice.lan.compose.yaml \
  -f /etc/cylo/voice.bridge.compose.yaml \
  up -d --no-build --pull never --no-deps voice-gateway
```

The original compose files and `/etc/cylo/voice.env` were left unchanged. The existing `/var/lib/cylo/voice:/app/data` mount, `cylo` network, `voice:voice` runtime identity, read-only root, capability restrictions, and both `127.0.0.1:18090` and existing `192.168.1.4:18090` bindings are preserved. Container environment values match the original compose/runtime configuration; only their ordering changed.

Immediately before replacement, the old gateway was stopped and SQLite's backup API created a consistent backup of `/var/lib/cylo/voice/voice.db` under `/var/backups/llm-auth-bridge/voice-pre-bridge-20261024T142834Z/`. The directory is mode 0700 and backup/rollback files are mode 0600, outside Git. The matching original environment and encryption key remain in place. A local `rollback.sh` in that directory records the complete stop, preserve-current-database, restore-backup, and restore-original-image procedure. **Rollback requires the matching pre-upgrade database and old image together:** startup seals legacy proxy fields, so switching only the binary back is unsafe. Preserve the post-upgrade database and sidecars before restoration; never overwrite them while the gateway is running.

The fork's Go tests passed, and the disposable HTTP acceptance against a separate fresh synthetic database at `127.0.0.1:18991` passed twice before deployment. The live replacement passed `/login` HTTP 200, unauthenticated capabilities/account GET/account PUT HTTP 401, and container health checks. Bridge app and worker health checks remained healthy. No accounts were written to the live gateway, no provider requests or real-account logins were performed, and no production database contents were inspected. The main operator then verified authenticated capabilities with the existing native administrator credentials: HTTP 200, `protocol=bridge-v1`, `explicit_route=true`, and `credential_digest=true`. The encrypted local voice target (ID 2) uses `http://cylo-voice-gateway:8090`, `allow_http=true`, and compatibility `bridge-v1`; the bridge target connection test returned HTTP 200. Worker-side DNS/network access to that same internal URL returned unauthenticated HTTP 401. No account writes, token probes, provider logins, or voice sessions were performed; real-account/provider acceptance remains **unverified**.

## Source-only worker refresh (2026-10-24)

The login challenge and takeover fixes at source revision `5e7417c0fff7f0018d7bcc863433bbf4597a78bf` passed the combined synthetic suite (152 passed, one opt-in voice harness skipped), 30 frontend tests, type checking, and production build. `pyproject.toml`, `uv.lock`, the standard Dockerfile, and Compose runtime configuration are unchanged from `3e4b0e8`. The standard app image built successfully; the redundant worker dependency build was cancelled during a slow Playwright download before any running service was replaced.

`deploy/worker-source-update.Dockerfile` reproduces the worker source refresh using the existing verified runtime image ID `sha256:b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380`. Docker resolves raw image IDs in `FROM` as repository references, so the recipe uses a local alias whose immutable ID must be checked immediately before building. Do not use this fallback when dependency or runtime configuration files have changed. It inherits the existing non-root user, entrypoint, browser dependencies, sandbox settings, and worker command, and only replaces reviewed application source and rebuilt frontend assets.

```sh
BASE_ID=sha256:b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380
BASE_ALIAS=llm-auth-bridge/worker-base:sha256-b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380
docker image tag "$BASE_ID" "$BASE_ALIAS"
test "$(docker image inspect "$BASE_ALIAS" --format '{{.Id}}')" = "$BASE_ID"
docker build --pull=false -f deploy/worker-source-update.Dockerfile \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -t llm-auth-bridge-worker:latest .
docker compose up -d --no-build --no-deps --wait app worker
```

Use the existing `.env` with `COMPOSE_FILE=docker-compose.yml:deploy/voice-network.compose.yml`; retain the data volume and both default/cylo networks. Do not recreate the separately managed voice gateway. Replacing the worker closes its live browser and can interrupt an active authorization; start a new authorization when required. Encrypted persisted sessions remain in the existing volume. Verify deployed source hashes, installed dependency versions, served asset bytes, and service health after replacement. These synthetic checks do not verify real-account login or explain a provider's password rejection.
