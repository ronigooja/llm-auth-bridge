"""Contract tests for the server release orchestrator using fake executables."""
from __future__ import annotations
import os, subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "deploy/release.sh"
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def make_harness(tmp_path: Path, *, failure: str | None = None, low_disk=False):
    bin = tmp_path / "bin"; bin.mkdir(); log = tmp_path / "calls.log"
    def exe(name, body):
        p = bin / name; p.write_text("#!/bin/sh\n" + body); p.chmod(0o755)
    exe("flock", "cat >/dev/null; exit 0")
    exe("ss", "exit 0")
    exe("df", "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'; echo \"x 1 1 %s 1%% /\"" % ("1" if low_disk else "99999999"))
    exe("curl", "echo '<html><script src=\"/app.js\"></script><link rel=\"stylesheet\" href=\"/app.css\"></html>'; exit 0")
    exe("timeout", "shift 3; exec \"$@\"")
    exe("docker", f'''echo docker "$@" >>"{log}"
if [ "$1" = info ]; then [ "$3" = DockerRootDir ] && echo /var/lib/docker || echo amd64; exit 0; fi
if [ "$1" = image ]; then echo "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; exit 0; fi
if [ "$1" = volume ]; then exit 1; fi
if [ "$1" = compose ]; then
  case "$*" in
    *pull*) [ "{failure}" = pull ] && exit 1;;
    *run*) [ "{failure}" = migrate ] && exit 1; echo 5;;
    *up*) [ "{failure}" = unhealthy ] && exit 1;;
    *ps\\ -q*) echo candidate;;
    *ps*) echo '{{}}';;
    *logs*|*stop*) :;;
  esac
  exit 0
fi
if [ "$1" = inspect ]; then echo '{{}}'; exit 0; fi
''')
    hooks = {}
    for name in ("snapshot", "switch", "rollback", "resume", "stop", "probe", "cert"):
        p = tmp_path / name; p.write_text(f"#!/bin/sh\necho {name} >>'{log}'\n" + (f"mkdir -p '$RELEASE_BACKUP_DIR'; : > '$RELEASE_BACKUP_DIR/bridge.sqlite3'\n" if name == "snapshot" else "")); p.chmod(0o755); hooks[name] = str(p)
    env = {"PATH": str(bin)+":"+os.environ["PATH"], "APP_IMAGE": f"ghcr.io/x/y@{DIGEST}", "WORKER_IMAGE": f"ghcr.io/x/y@{DIGEST}", "RELEASE_COMMIT": SHA, "FAST_GATE_SHA": SHA, "FAST_GATE_URL": "https://ci/run", "PUBLIC_URL": "https://bridge.example", "MASTER_KEY_FILE": str(tmp_path/"key"), "RELEASE_PROJECT": "bridge-test", "RELEASE_STATE_DIR": str(tmp_path/"state")}
    Path(env["MASTER_KEY_FILE"]).write_bytes(b"k")
    for k,v in hooks.items(): env[k.upper()+"_HOOK"] = v
    return env, log


def run(tmp_path, failure=None, low_disk=False):
    env, log = make_harness(tmp_path, failure=failure, low_disk=low_disk)
    return subprocess.run([str(SCRIPT)], env=env, text=True, capture_output=True), log


def test_pull_failure_does_not_resume_old(tmp_path):
    result, log = run(tmp_path, "pull")
    assert result.returncode
    assert "resume" not in log.read_text()


def test_migrate_failure_resumes_without_switch(tmp_path):
    result, log = run(tmp_path, "migrate")
    calls = log.read_text()
    assert result.returncode and "resume" in calls and "switch" not in calls


def test_unhealthy_failure_resumes_without_switch(tmp_path):
    result, log = run(tmp_path, "unhealthy")
    calls = log.read_text()
    assert result.returncode and "resume" in calls and "switch" not in calls


def test_low_disk_stops_before_snapshot(tmp_path):
    result, log = run(tmp_path, low_disk=True)
    assert result.returncode and "snapshot" not in log.read_text()
