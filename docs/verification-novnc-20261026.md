# Account viewer cookie regression verification

## Change

The account popup now navigates to the authenticated `/account-window` HTML
shell before the parent renders the embedded noVNC viewer. A real same-site
host document preserves Strict session cookies for the viewer subresources
in WebKit. Previously the live server returned 200 for `vnc.html` but 401
for its stylesheet, scripts and images, exposing the unstyled error heading
and hidden control panels. Authentication and cookie settings remain enforced.
The ambiguous idle-window session-ending hint was removed.

## Hosted results

Source: `0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92`.
No uncommitted input was reported by either runner.

[Viewer regression run 40286461306](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40286461306)
on Ubuntu 24.04 passed 58 frontend tests, built the production frontend,
and passed 65 backend tests. Four packaged noVNC acceptance cases passed:
direct and account-popup viewers in Chromium and WebKit, using the production
Debian noVNC 1.3.0 package and the non-loopback HTTP hostname `bridge.test`.
They verify a connected framebuffer, read-only monitoring, hidden error/power
panels, successful required resource requests, and unchanged task execution.
Debian omits the optional `package.json` version metadata; only that expected
404 is excluded from the failed-resource check. Both recorded exits are 0.

[Deployment run 40288386352](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40288386352)
passed 465 backend tests with one opt-in skip and built native ARM64 app and
worker images. Selected browser acceptance passed 46 cases, skipped two
opt-in WebKit cases (covered separately by the viewer regression run), and
deselected 30. The browser acceptance and image jobs both succeeded.
The workflow files retain the exact commands and execution deadlines.
No local compilation, image build or automated test was performed.

Collected logs and artifacts are retained at
`/tmp/bridge-novnc-fix-20261026/` on the deployment controller, under
`run-40286461306/` and `deployment-40288386352/` respectively.
No credentials, database, browser state, recordings or real-account provider
logins were used for this verification. Real-account acceptance remains
unverified.

## Deployed app

[Export run 40293483854](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40293483854)
retrieved the successful deployment image artifact, checked its checksum,
and exported only the existing ARM64 app image, without rebuilding it.
The export exit was 0. The separate app archive checksum passed locally;
`docker load -i app.tar.gz` exited 0. A rollback tag retains the previous app
image as `llm-auth-bridge-app:rollback-novnc-20261026`.

The deployment command was:

```sh
docker compose -f docker-compose.yml -f deploy/voice-network.compose.yml up -d --no-build --pull never --no-deps --wait app
```

It exited 0 and the app is healthy. The runtime source revision label is
`0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92`; its loaded image ID is
`sha256:251d7e7eb8ff9b003d1e867ec1ff11b26dc9b3647b12655ebb6f98871810661e`.
The app handler file matches the reviewed source hash, and all three served
frontend files match the tested CI artifact byte for byte. `/readyz` returns
200; unauthenticated shell and noVNC stylesheet requests return 401.
Worker and Voice gateway container IDs, image IDs and start times were
unchanged. No database migration was required. The combined app/worker image
download was stopped in favor of the smaller app-only export.

Deployment logs, actual exits, image/source identities, rollback information,
and served frontend hashes are saved under
`/tmp/bridge-novnc-fix-20261026/`. This confirms artifact deployment and
synthetic viewer acceptance; real-account acceptance remains unverified.
