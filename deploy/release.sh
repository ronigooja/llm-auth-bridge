#!/usr/bin/env bash
# Run on the target Linux server for an already gated release, never locally.
set -Eeuo pipefail
umask 077
for name in APP_IMAGE WORKER_IMAGE RELEASE_COMMIT FAST_GATE_URL FAST_GATE_SHA PUBLIC_URL MASTER_KEY_FILE RELEASE_PROJECT \
  SNAPSHOT_HOOK SWITCH_HOOK ROLLBACK_HOOK RESUME_OLD_HOOK STOP_OLD_HOOK PROBE_HOOK CERT_CHECK_HOOK; do
  [[ -n ${!name:-} ]] || { echo "Missing configuration: $name" >&2; exit 2; }
done
for image in "$APP_IMAGE" "$WORKER_IMAGE"; do
  [[ $image =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || { echo 'Images must use GHCR SHA256 digests' >&2; exit 2; }
done
[[ $RELEASE_COMMIT =~ ^[a-f0-9]{40}$ && $FAST_GATE_SHA = "$RELEASE_COMMIT" && $RELEASE_PROJECT =~ ^bridge-[a-z0-9-]+$ ]] || exit 2
[[ $FAST_GATE_URL =~ ^https://[^[:space:]]+$ ]] || exit 2
[[ $PUBLIC_URL =~ ^https://[^/]+$ ]] || { echo 'PUBLIC_URL must be an HTTPS origin' >&2; exit 2; }
for name in SNAPSHOT_HOOK SWITCH_HOOK ROLLBACK_HOOK RESUME_OLD_HOOK STOP_OLD_HOOK PROBE_HOOK CERT_CHECK_HOOK; do
  [[ ${!name} = /* && -x ${!name} ]] || { echo "$name must be an absolute executable path" >&2; exit 2; }
done
export APP_IMAGE WORKER_IMAGE MASTER_KEY_FILE CANDIDATE_PORT=${CANDIDATE_PORT:-18000}
[[ $CANDIDATE_PORT =~ ^[0-9]+$ ]] && (( CANDIDATE_PORT > 1024 && CANDIDATE_PORT < 65536 )) || exit 2
[[ -r $MASTER_KEY_FILE ]] || exit 2
for command in docker curl python3 timeout flock ss; do command -v "$command" >/dev/null; done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
state_dir=${RELEASE_STATE_DIR:-/var/lib/llm-auth-bridge/releases}
mkdir -p "$state_dir"
exec 9>"$state_dir/deployment.lock"
flock -n 9 || { echo 'Another deployment is active' >&2; exit 1; }
record="$state_dir/$RELEASE_PROJECT"
mkdir "$record" # Refuse reuse of a candidate project or deployment record.
export RELEASE_BACKUP_DIR="$record/import"
mkdir "$RELEASE_BACKUP_DIR"
chmod 755 "$record" "$RELEASE_BACKUP_DIR"
compose=(docker compose -p "$RELEASE_PROJECT" -f "$script_dir/release.compose.yml")
changed=0
switched=0
accepted=0
finish() {
  rc=$?
  trap - EXIT
  if (( rc != 0 && accepted == 0 )); then
    if (( switched )); then timeout -k 10s 60s "$ROLLBACK_HOOK" >>"$record/rollback.log" 2>&1 || echo 'Traffic rollback failed; operator action required' >&2; fi
    "${compose[@]}" logs --no-color --tail 100 app worker >"$record/containers.log" 2>&1 || true
    "${compose[@]}" stop >>"$record/rollback.log" 2>&1 || true
    if (( changed )); then timeout -k 10s 60s "$RESUME_OLD_HOOK" >>"$record/rollback.log" 2>&1 || echo 'Old service resume failed; operator action required' >&2; fi
    echo 'failed' >"$record/result"
  fi
  # Preserve failed import backups for diagnosis; successful imports are disposable.
  if (( accepted )); then rm -rf -- "$RELEASE_BACKUP_DIR"; fi
  exit "$rc"
}
trap finish EXIT
exec >"$record/deployment.log" 2>&1
printf 'commit=%s\napp=%s\nworker=%s\nfast_gate=passed\nfast_gate_run=%s\nfull_pytest=not_run\nreal_account=unverified\nrenewal=unverified\nvoice_call=unverified\n' "$RELEASE_COMMIT" "$APP_IMAGE" "$WORKER_IMAGE" "$FAST_GATE_URL" >"$record/acceptance.txt"
docker info >/dev/null
docker compose version
[[ $(docker info --format '{{.Architecture}}') =~ ^(x86_64|amd64)$ ]]
# Require room for both current and candidate images; override only for measured hosts.
docker_root=$(docker info --format '{{.DockerRootDir}}')
available_kb=$(df -Pk "$state_dir" | awk 'NR==2 {print $4}')
docker_available_kb=$(df -Pk "$docker_root" | awk 'NR==2 {print $4}')
(( available_kb >= ${MIN_FREE_KB:-10485760} && docker_available_kb >= ${MIN_FREE_KB:-10485760} ))
awk -v minimum="${MIN_MEMORY_KB:-4194304}" '/MemTotal:/ {exit !($2 >= minimum)}' /proc/meminfo
if ss -H -ltn "sport = :$CANDIDATE_PORT" | grep -q .; then echo "candidate port is already in use" >&2; exit 2; fi
timeout -k 10s 60s "$CERT_CHECK_HOOK"
# Private registries require docker login --password-stdin before invoking this script.
timeout -k 15s 300s "${compose[@]}" pull
candidate_volume="${RELEASE_PROJECT}_app-data"
if docker volume inspect "$candidate_volume" >/dev/null 2>&1; then echo "candidate volume already exists: $candidate_volume" >&2; exit 2; fi
# Pull by digest, then verify the immutable image labels identify this source commit.
for image in "$APP_IMAGE" "$WORKER_IMAGE"; do
  revision=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [[ $revision = "$RELEASE_COMMIT" ]] || { echo "image revision label mismatch: $image" >&2; exit 2; }
done
changed=1
timeout -k 10s 120s "$SNAPSHOT_HOOK"
# Snapshot hook must quiesce writes and create a consistent key-matched archive.
[[ -f $RELEASE_BACKUP_DIR/bridge.sqlite3 ]]
chmod 644 "$RELEASE_BACKUP_DIR/bridge.sqlite3"
timeout -k 10s 120s "${compose[@]}" run --rm --no-deps -v "$RELEASE_BACKUP_DIR:/import:ro" app python -m app.cli restore /import/bridge.sqlite3
timeout -k 10s 120s "${compose[@]}" run --rm --no-deps app python -m app.cli migrate
timeout -k 15s 180s "${compose[@]}" up -d --wait --wait-timeout 150
curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$CANDIDATE_PORT/readyz" >"$record/readyz.json"
# A switch may fail after partially changing traffic, so arm rollback first.
switched=1
timeout -k 10s 60s "$SWITCH_HOOK"
curl --fail --silent --show-error --max-time 20 "$PUBLIC_URL/readyz" >"$record/public-readyz.json"
curl --fail --silent --show-error --max-time 20 "$PUBLIC_URL/" >"$record/index.html"
# Check all bundled JS/CSS entry assets discovered in the served page.
python3 - "$record/index.html" >"$record/assets.txt" <<'PY'
from html.parser import HTMLParser
import sys
from urllib.parse import urlsplit
class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        path = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' and values.get('rel') == 'stylesheet' else None
        if path:
            parsed = urlsplit(path)
            if parsed.scheme or parsed.netloc or not path.startswith('/') or path.startswith('//'):
                raise ValueError('Expected same-origin absolute asset path')
            print(path)
Assets().feed(open(sys.argv[1]).read())
PY
[[ -s $record/assets.txt ]]
while IFS= read -r asset; do curl --fail --silent --show-error --max-time 15 "$PUBLIC_URL$asset" >/dev/null; done <"$record/assets.txt"
redirect=$(curl --silent --show-error --max-time 15 -o /dev/null -w '%{http_code} %{redirect_url}' "http://${PUBLIC_URL#https://}/")
[[ $redirect =~ ^30[1278]\ https:// ]]
# Hook checks authenticated synthetic SSE/WebSocket and configured CPA/Voice management.
timeout -k 10s 90s "$PROBE_HOOK" >"$record/synthetic-probes.log" 2>&1
"${compose[@]}" ps --format json >"$record/containers.json"
"${compose[@]}" run --rm --no-deps app python -c 'import os,sqlite3; c=sqlite3.connect(os.environ["LLM_AUTH_DB"]); print(c.execute("PRAGMA user_version").fetchone()[0])' >"$record/schema-version.txt"
for service in app worker; do
  container=$("${compose[@]}" ps -q "$service")
  docker inspect "$container" --format '{{.Config.Image}} {{.Image}} {{.State.Health.Status}}' >>"$record/running-images.txt"
done
printf 'online_health=passed\nhttps=passed\ncertificate=passed\nsynthetic_probes=passed\n' >>"$record/acceptance.txt"
# From this point the new service is authoritative; cleanup failure must not roll data back.
accepted=1
printf 'accepted\n' >"$record/result"
timeout -k 15s 120s "$STOP_OLD_HOOK"
printf 'old_bridge=stopped; old_database_key_config=retained\n' >>"$record/acceptance.txt"
