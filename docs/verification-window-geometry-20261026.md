# Account window clipping repair

## Cause

The deployed worker profile uses a 1760×900 webpage viewport and a
1920×1080 screen. Its inherited `/usr/local/bin/bridge-worker` entrypoint
still started Xvfb at 1440×900. The webpage's right and bottom edges therefore
fell outside the VNC framebuffer. Client-side scaling cannot restore pixels
that were never part of that framebuffer.

The repository Dockerfile already specifies a 1920×1080 desktop. Earlier
source-only worker refreshes retained the old entrypoint, and the latest noVNC
cookie fix updated only the app. This repair deploys the complete verified
worker image rather than refreshing its Python files.

## Hosted validation

[Viewer regression run 40295798431](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40295798431)
at workflow source `2879826b6ff51739eba8ce2a5d837c945d5f960e` passed 58 frontend
tests, the production frontend build, 65 backend pytest cases, and four packaged
noVNC browser acceptance cases in Chromium and WebKit. Both recorded validation
exits are zero. This is targeted synthetic regression, not a complete pytest
suite or real-account acceptance.

[Export run 40295797422](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40295797422)
retrieved the worker image from successful deployment run `40288386352`, verified
the archive checksum, ARM64 architecture and source revision
`0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92`, then checked the extracted worker
entrypoint for the exact 1920×1080 Xvfb command before exporting it. No image was
rebuilt on the controller. Export artifact ID: `12637499280`.

Evidence is retained under `/tmp/bridge-window-geometry-20261026/` on the
controller. No credentials, browser state, screenshots, recordings or database
copies were collected. Real-account acceptance remains unverified.

## Deployed result

The worker archive checksum passed and `docker load` exited zero. The loaded
image ID is
`sha256:92f27121077906e4289893095cf5fe40bbb11bbd2daae3c18faea06420691bee`.
The hosted Docker daemon recorded
`sha256:e39217d0c3452c061a6c84556d9c6698f9adb9b824ef44a70d77a6cbd10240e4`.
As in the earlier app deployment, the daemon image IDs differ. An independent
archive comparison confirmed identical image configuration, complete ordered
root filesystem layer diff IDs, operating system and architecture. Both images
retain the exact reviewed source revision label.

There were no active account tasks immediately before replacement. The previous
worker image is retained as
`llm-auth-bridge-worker:rollback-window-geometry-20261026`. The command was:

```sh
docker compose -f docker-compose.yml -f deploy/voice-network.compose.yml up -d --no-build --pull never --no-deps --wait worker
```

It exited zero. Worker container
`0bb07b97d7ece6dd6907c206fe40e2deb7ce78391e03fd8ed27cfb0f0e32a8ab`
is healthy. Reading the running Xvfb process command line confirmed
`Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp`. Application `/readyz`
returned HTTP 200 with `{"status":"ready"}`. App and Voice gateway container
IDs, image IDs and start times exactly match the pre-deployment record.
Existing Compose volume and network configuration were retained, and no
migration was performed. Close and reopen an existing account window to
reconnect its viewer to the replacement worker. Visual confirmation in the
operator's existing account remains pending.
