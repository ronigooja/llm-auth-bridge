# Native browser fills the account desktop

## Behavior

Enlarging Xvfb fixed clipped content but exposed unused desktop to the right
and bottom of the fixed-size browser. Headed sessions now use the native
viewport, with the outer browser window positioned at the available screen's
origin and sized to fill it. The webpage follows the remaining area below the
browser toolbar. This avoids hardcoding toolbar heights across Chromium
versions. Stored viewport and screen preferences remain readable, but those
emulation options and device scale factor are omitted for headed launches.
Account identity seeds, browser storage, locale and route timezone are preserved.

Restored maximized/minimized state and stale window bounds are reset through
Chromium's native window API before the task exposes its viewer. Viewer scaling
continues to preserve the desktop's aspect ratio.

## Hosted acceptance

Source: `cb0424eb51f636ff0798ad3ce30d9b895f29bda1`.
[Deployment run 40298981685](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40298981685)
passed 465 backend pytest cases with one opt-in skip, 58 frontend tests, the
production frontend build, and 46 selected browser acceptance cases with two
opt-in WebKit skips and 30 deselected cases. This is the deployment workflow's
partitioned validation, not a complete pytest run.

Headed Chromium acceptance fills the 1920×1080 desktop within one pixel of
native frame rounding, verifies that the content follows a smaller native
window, then restores an encrypted profile with those smaller saved bounds and
verifies full desktop coverage, storage preservation and account isolation.
The native window position must be (0, 0); large unused margins are rejected.
The collected intermediate geometry was 1919×1079 outer bounds and a
1919×936 native webpage viewport on a 1920×1080 screen. Earlier strict equality
incorrectly rejected this one-pixel native rounding and was corrected; the
production window code was unchanged by that test correction.

Evidence is retained under `/tmp/bridge-window-fill-20261026/` on the
controller. No local compilation, image build or automated test was run.
No credentials, database copies, provider logins, browser recordings or sensitive
screenshots were collected. Real-account visual acceptance remains unverified.

## Deployed worker

The native ARM64 image job succeeded. Artifact `12640535237` was downloaded,
its archive checksum verified, and its worker configuration, ordered root
filesystem layer diff IDs, architecture, OS and revision label compared with
the loaded image. Every comparison matched. The hosted worker image ID is
`sha256:0dca1f175ed3ac7f28f9bc1b4fe13304eb7930ce3c9764844d0db90c9cc29cba`;
the local daemon records
`sha256:5367a9febd977490c4f8802ed2a20609a0f3ed81a5f6920ad19c47010035b593`.
The same daemon identity representation difference was observed and audited in
previous deployments.

No active account task was present immediately before replacement. The prior
1920×1080 worker image is retained under
`llm-auth-bridge-worker:rollback-native-window-20261026`. The deployment command
was:

```sh
docker compose -f docker-compose.yml -f deploy/voice-network.compose.yml up -d --no-build --pull never --no-deps --wait worker
```

It exited zero. Worker container
`c644f53867aa76d0a9ea7f84f3e04b1556b13730f023b16263da913edb40ef54`
is healthy. Both changed production Python files match the reviewed source
hashes byte for byte, and application `/readyz` returns HTTP 200 with
`{"status":"ready"}`. App and Voice gateway container IDs, image IDs and
start times match the pre-deployment record. Existing volumes and networks
were retained; no database migration was required. Reopen the account window
to start a browser with the new native sizing behavior. Operator confirmation
of the existing account's visual result is pending.
