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

Schema v6 is the current schema. Migration is explicit and offline; app and worker must be stopped, and the existing encryption key must be used. Do not generate a replacement key for an existing database. Deploy app, worker, and frontend together.

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

## Voice gateway integration

Follow the [Voice gateway README](../../deploy/voice/README.md) for the pinned
source, image publication, installation, upgrade, acceptance, and paired
database/key rollback procedure. The bridge deployment must preserve the gateway
data mount, runtime UID, network, and hardening settings.

For a separately managed gateway on the existing `cylo` network, the optional
[network overlay](../../deploy/voice-network.compose.yml) joins the bridge to that
network without publishing gateway ports. Persist
`COMPOSE_FILE=docker-compose.yml:deploy/voice-network.compose.yml` in the ignored
`.env` and retain it for later operations. The network must already exist. A
container service URL such as `http://cylo-voice-gateway:8090` is distinct from
host loopback and has no `/login` suffix; trusted HTTP requires `allow_http: true`.
Do not recreate the independently managed gateway during bridge upgrades.

Run the Voice README's disposable acceptance procedure against a separate empty
database before changing production; keep synthetic credentials and account
writes away from live data.

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

## Immutable GHCR release procedure

A release is eligible for deployment only after the fast gate passes. The image workflow publishes separate amd64 app and worker images to GHCR with the commit SHA and emits their immutable `sha256` digests. The target server pulls those digests directly; do not use Actions artifacts or a developer laptop as image transport. Authenticate on the server with `docker login ghcr.io` before running [`deploy/release.sh`](../../deploy/release.sh), and supply `APP_IMAGE` and `WORKER_IMAGE` as `ghcr.io/owner/repository@sha256:...` values.

The server needs Docker Engine with Compose v2, amd64 Linux, at least 10 GiB free on the release filesystem and 4 GiB RAM, an existing UID-readable master key, a renewing HTTPS certificate, and ports 80/443 available to the reverse proxy. The release project uses [`deploy/release.compose.yml`](../../deploy/release.compose.yml), a private candidate port, the existing seccomp profile, non-root containers, and `/readyz` health checks. Configure the reverse proxy with the existing WebSocket upgrade routes and buffering disabled for task SSE; set proxy read/send timeouts to at least 3600 seconds for account-window and SSE operations.

The script requires executable operator hooks for the current bridge snapshot, traffic switch, synthetic HTTPS/API/WebSocket/SSE/CLIProxyAPI/Voice probes, certificate check, old-service resume, old-service stop, and traffic rollback. It first checks Docker, resources, certificate renewal, and port availability, pulls both digests, snapshots the current database, restores that snapshot into a new candidate volume, runs offline `migrate`, and waits for app and worker health. It switches traffic with rollback armed, then checks the HTTPS redirect, homepage, same-origin JS/CSS assets, `/readyz`, and the synthetic probes.

A failed pull, migration, startup, health check, asset check, or probe stops the candidate and resumes the old bridge. The old database, key, reverse-proxy configuration, Voice service, CLIProxyAPI service, and unrelated volumes remain untouched. After all checks pass, the script records running image digests, schema version, container state and health results, then stops the old bridge. Successful temporary imports are removed; failed imports remain under the release state directory for diagnosis. Keep the release record and rollback image until the next accepted release.

## Acceptance record

For every release, preserve a record containing the commit, app and worker digests, fast-gate result, complete pytest state, migration result and schema version, app/worker health, HTTPS and certificate result, synthetic endpoint result, and whether real login, long-term renewal, or Voice calls were verified. A release with `full_pytest=not run` is eligible only when the fast gate and online checks pass; it must not be described as a full regression pass.

### Required release hook configuration

The script intentionally delegates site-specific traffic and management details to executable hooks. Set `FAST_GATE_URL` to the successful fast-gate workflow URL and `FAST_GATE_SHA` to the same commit as `RELEASE_COMMIT`; the script checks the GitHub API for a completed successful gate on that revision and rejects mismatched workflow provenance. For private repositories, provide a read-only `GH_TOKEN` to this server-side check. Set `SNAPSHOT_HOOK` to stop/quiesce the old bridge and write the key-matched SQLite snapshot to `$RELEASE_BACKUP_DIR/bridge.sqlite3`. `SWITCH_HOOK` changes the reverse proxy upstream to the candidate port, `ROLLBACK_HOOK` restores the old upstream, `RESUME_OLD_HOOK` starts the old bridge after a failed candidate, and `STOP_OLD_HOOK` stops it after acceptance. `CERT_CHECK_HOOK` checks certificate validity and automatic renewal, while `PROBE_HOOK` runs authenticated synthetic checks for `/readyz`, task WebSocket/SSE, CLIProxyAPI management, and Voice management. Hooks must be absolute executable paths and should fail closed.

The order is: pull and label verification; snapshot and offline restore/migrate; candidate app/worker health; switch traffic; public HTTPS redirect/homepage/static asset and synthetic endpoint checks; record digests/schema/health; stop the old bridge. Public checks run after the switch so they exercise the new site. A failed check after switching invokes `ROLLBACK_HOOK` before stopping the candidate.

Example environment (values are placeholders and must be replaced on the target host):

```sh
export RELEASE_PROJECT=bridge-20261029
export RELEASE_COMMIT='<40-hex-commit>'
export FAST_GATE_SHA="$RELEASE_COMMIT"
export FAST_GATE_URL='https://github.com/<owner>/<repo>/actions/runs/<run-id>'
export APP_IMAGE='ghcr.io/<owner>/<repo>-app@sha256:<64-hex-digest>'
export WORKER_IMAGE='ghcr.io/<owner>/<repo>-worker@sha256:<64-hex-digest>'
export MASTER_KEY_FILE=/var/lib/llm-auth-bridge/secrets/master_key
export PUBLIC_URL=https://bridge.example.com
export SNAPSHOT_HOOK=/usr/local/libexec/bridge-snapshot
export SWITCH_HOOK=/usr/local/libexec/bridge-switch
export ROLLBACK_HOOK=/usr/local/libexec/bridge-rollback
export RESUME_OLD_HOOK=/usr/local/libexec/bridge-resume-old
export STOP_OLD_HOOK=/usr/local/libexec/bridge-stop-old
export PROBE_HOOK=/usr/local/libexec/bridge-probe
export CERT_CHECK_HOOK=/usr/local/libexec/bridge-cert-check
sudo --preserve-env=APP_IMAGE,WORKER_IMAGE,RELEASE_COMMIT,FAST_GATE_SHA,FAST_GATE_URL,MASTER_KEY_FILE,RELEASE_PROJECT,PUBLIC_URL,SNAPSHOT_HOOK,SWITCH_HOOK,ROLLBACK_HOOK,RESUME_OLD_HOOK,STOP_OLD_HOOK,PROBE_HOOK,CERT_CHECK_HOOK ./deploy/release.sh
```

When configuring a new target, record its hostname, candidate port, image digests, reverse-proxy timeouts, certificate renewal mechanism and resource checks outside Git. This repository provides orchestration and hook contracts; no production host, authenticated probe implementation or real-account acceptance is bundled. Keep old data, keys and configuration until an operator accepts the rollback retention period. Never remove Voice, CLIProxyAPI or unrelated volumes during bridge cleanup.
