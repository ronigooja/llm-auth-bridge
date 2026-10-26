# Adaptive account viewer acceptance and deployment

## Corrected behavior

A fixed 1920×1080 desktop displayed with local scaling necessarily leaves bars
when the account popup has another aspect ratio and changes the apparent font
size. Selecting remote resizing could not fix the old Xvfb/x11vnc desktop, and
noVNC 1.3 suppresses resize requests for read-only clients.

The account popup now embeds the authenticated `/account-viewer`. It resizes
the TigerVNC desktop to the iframe's CSS dimensions and renders the framebuffer
at 1:1 CSS scale, with no scaling settings menus. Openbox keeps the native
Chromium window maximized as the desktop changes size. The monitor permits only
bounded single-screen geometry requests; keyboard, pointer and clipboard input
remain blocked. See [transport contract](browser-window.md).

## Hosted evidence

Production source: `e55ae999dfc821eb41aee3818285dace0830779e`.
[Deployment run 40304619566](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40304619566)
passed 476 backend pytest cases with one opt-in skip, 58 frontend tests and the
production frontend build. Selected browser acceptance passed 46 cases, with
two opt-in WebKit skips and 30 deselected cases. Native ARM64 app and worker
images built successfully. Inside the actual worker image, as the nonroot user
with production sandbox restrictions, an RFB client resized the desktop to
1100×820, 1400×700 and 900×1000; the browser followed each size while preserving
16px text and native DPR 1. This is partitioned acceptance, not a full pytest run.

[Retina viewer run 40305857158](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40305857158)
at `b51eb0469917f2483e0ea10bd9af19cf4d02f391` passed four packaged noVNC cases,
58 frontend tests, the frontend build and 67 backend cases. Account popups were
resized through 1100×900, 1400×760 and 900×1000 in Chromium and WebKit. WebKit
used client DPR 2 to cover Retina display scale. Checks require framebuffer
and CSS canvas dimensions to match the iframe within one pixel of layout
rounding, no canvas transform scaling or crop, matching native desktop/browser
size, and unchanged 16px text. They also check read-only mode, no settings menus,
required assets, task ownership and uninterrupted task state.

The Retina revision changes only the test and its workflow; production files
are identical to the image source. A preceding run stalled downloading a font
from the hosted runner's Azure Ubuntu mirror before browser checks could run.
The workflow now selects the Ubuntu archive mirror, bounds download retries,
and caches installed viewer browsers.

## Deployment

Artifact `12642037473` passed its archive checksum. Both loaded image
configurations, complete ordered layer diff IDs, architecture, OS and revision
labels match the archive. Local image IDs are app
`sha256:62166f6a6c6961c601fc536141711732185869861921c5a3f4a6b83aa8dc5cfd`
and worker
`sha256:54bfc028466a068cbb3002f9a74b66371af85e35c9c88d09027b8da69efeb0de`.
Hosted daemon image IDs differ as in prior deployments; the configuration and
layer audit confirms content identity.

No account task was active immediately before replacement. Scheduled maintenance
was disabled during replacement and restored to its original enabled state.
Previous running images retain `rollback-adaptive-viewer-20261026` tags for each
service. The command was:

```sh
docker compose -f docker-compose.yml -f deploy/voice-network.compose.yml up -d --no-build --pull never --wait app worker
```

It exited zero. App `cd8e810ec2a7a5eb02c201a8bc347459b97485944bbe3a99269820770f48c24d`
and worker `05c62bab0c25d522046f55cb9d875070a84a1d27af27be75de73fa8c52be09eb`
are healthy, and `/readyz` returns HTTP 200. Changed Python sources and both
viewer files in each service match the reviewed source byte for byte. Both
served frontend assets match the successful hosted Retina artifact. Viewer HTML
and JavaScript return 401 without authentication. Voice gateway container ID,
image and start time are unchanged. Existing volumes, networks and master key
were retained; no migration was required.

Refresh the management page before reopening the account window so the browser
loads the new viewer URL. Synthetic checks do not establish physical Safari or
real-account provider acceptance; operator visual confirmation remains pending.
No real credentials, browser archives, database copies, screenshots, tracing,
HAR or videos were collected. No builds or automated tests ran on the controller.
Evidence is retained under `/tmp/bridge-adaptive-viewer-20261026/`; downloaded
image archives were removed after integrity checks and successful loading to
bound disk usage, while logs, checksum manifests, installed images and rollback
tags were retained.
