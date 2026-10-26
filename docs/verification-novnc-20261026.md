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
worker images. The browser acceptance and image jobs both succeeded.
The workflow files retain the exact commands and execution deadlines.
No local compilation, image build or automated test was performed.

Collected logs and artifacts are retained at
`/tmp/bridge-novnc-fix-20261026/` on the deployment controller, under
`run-40286461306/` and `deployment-40288386352/` respectively.
No credentials, database, browser state, recordings or real-account provider
logins were used for this verification. Real-account acceptance remains
unverified.
