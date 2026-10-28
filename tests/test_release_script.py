"""Release orchestration tests with deterministic fake host commands (Linux CI)."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
SCRIPT = Path(__file__).parents[1] / 'deploy/release.sh'; SHA='a'*40; DIGEST='sha256:'+'b'*64
DISPATCH = r'''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
name=os.path.basename(sys.argv[0]); args=sys.argv[1:]; log=os.environ['FAKE_LOG']
def rec(x):
 with open(log,'a') as f: f.write(json.dumps(x)+'\n')
rec([name,*args])
fail=os.environ.get('FAIL','')
if name=='timeout': os.execvp(args[3],args[3:])
if name=='flock': sys.exit(0)
if name=='ss': sys.exit(0)
if name=='awk':
 print('MemTotal:       8000000 kB' if '/proc/meminfo' in args else '99999999'); sys.exit(0)
if name=='df': print('Filesystem 1024-blocks Used Available Capacity Mounted on\nx 1 1 '+('1' if os.environ.get('LOW_DISK') else '99999999')+' 1% /'); sys.exit(0)
if name=='curl': print('<html><script src="/app.js"></script><link rel="stylesheet" href="/app.css"></html>'); sys.exit(0)
if name=='docker':
 if args[:1]==['info']:
  print('/var/lib/docker' if '--format' in args and 'DockerRootDir' in args[-1] else 'amd64'); sys.exit(0)
 if args[:2]==['volume','inspect']: sys.exit(0 if os.environ.get('COLLISION') else 1)
 if args[:1]==['image']: print('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'); sys.exit(0)
 if args[:1]==['inspect']: print('ghcr.io/x/y@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb healthy'); sys.exit(0)
 if args[:1]==['compose']:
  text=' '.join(args)
  if fail and fail in text: sys.exit(1)
  if 'run' in text and 'migrate' in text: print('5')
  elif 'ps' in text: print('{}')
  sys.exit(0)
 sys.exit(0)
if name in ('snapshot','switch','rollback','resume','stop','probe','cert'):
 if name=='snapshot': Path(os.environ['RELEASE_BACKUP_DIR']).mkdir(parents=True,exist_ok=True); Path(os.environ['RELEASE_BACKUP_DIR'],'bridge.sqlite3').touch()
 sys.exit(0)
sys.exit(0)
'''
def setup(tmp, fail='', low=False, collision=False):
 b=tmp/'bin'; b.mkdir(); log=tmp/'calls'; (tmp/'key').write_bytes(b'k')
 for n in ('docker','curl','awk','df','ss','flock','timeout','snapshot','switch','rollback','resume','stop','probe','cert'):
  p=b/n; p.write_text(DISPATCH); p.chmod(0o755)
 env=os.environ.copy(); env.update(PATH=str(b)+':'+env['PATH'],FAKE_LOG=str(log),FAIL=fail,LOW_DISK='1' if low else '',COLLISION='1' if collision else '',APP_IMAGE=f'ghcr.io/x/y@{DIGEST}',WORKER_IMAGE=f'ghcr.io/x/y@{DIGEST}',RELEASE_COMMIT=SHA,FAST_GATE_SHA=SHA,FAST_GATE_URL='https://ci/run',PUBLIC_URL='https://bridge.example',MASTER_KEY_FILE=str(tmp/'key'),RELEASE_PROJECT='bridge-test',RELEASE_STATE_DIR=str(tmp/'state'),SNAPSHOT_HOOK=str(b/'snapshot'),SWITCH_HOOK=str(b/'switch'),ROLLBACK_HOOK=str(b/'rollback'),RESUME_OLD_HOOK=str(b/'resume'),STOP_OLD_HOOK=str(b/'stop'),PROBE_HOOK=str(b/'probe'),CERT_CHECK_HOOK=str(b/'cert'))
 return env,log
def run(tmp,**kw):
 env,log=setup(tmp,**kw); return subprocess.run([str(SCRIPT)],env=env,text=True,capture_output=True),log
def calls(log): return [json.loads(x)[0] for x in log.read_text().splitlines()] if log.exists() else []
def test_pull_failure_no_resume(tmp_path):
 r,l=run(tmp_path,fail='pull'); assert r.returncode and 'resume' not in calls(l)
def test_migrate_failure_resumes_before_switch(tmp_path):
 r,l=run(tmp_path,fail='migrate'); c=calls(l); assert r.returncode and c.index('resume')>c.index('snapshot') and 'switch' not in c
def test_unhealthy_failure_resumes(tmp_path):
 r,l=run(tmp_path,fail='up'); assert r.returncode and 'resume' in calls(l) and 'switch' not in calls(l)
def test_low_disk_before_snapshot(tmp_path):
 r,l=run(tmp_path,low=True); assert r.returncode and 'snapshot' not in calls(l)
def test_existing_candidate_refused_without_stop(tmp_path):
 r,l=run(tmp_path,collision=True); assert r.returncode and 'stop' not in calls(l)
def test_success_switches_then_probes_and_stops(tmp_path):
 r,l=run(tmp_path); c=calls(l); assert r.returncode, r.stderr; assert c.index('switch')<c.index('probe')<c.index('stop')
def test_static_asset_failure_rolls_back(tmp_path):
 # A failed public asset request is represented by a failed curl after switch.
 env,log=setup(tmp_path); env['FAIL']='curl'; r=subprocess.run([str(SCRIPT)],env=env,text=True); c=calls(log); assert r.returncode and 'rollback' in c and 'resume' in c
