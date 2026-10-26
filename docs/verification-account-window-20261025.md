# Account window and session continuation validation

## Scope and source

Implementation integrates independent ChatGPT and Codex login actions, durable
Web-before-Codex dependencies, account-scoped persistent browser windows,
authenticated read-only monitoring, and safe existing-account/consent continuation.
The code and workflow revision before this evidence-only record is
`16fc73d`. No new production deployment or real-account login was performed for
these changes. No backup or rollback image tag was created.

## Collected results

Hosted run [40234606903](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40234606903)
at source `f9eaacd51c60323a31b42146369bf536beeb6d8c` completed the targeted
Codex continuation suite with **23 passed**, 31 deselected, in 81.91 seconds,
actual exit status **0**. Its command was:

```sh
timeout --kill-after=10s 180s uv run pytest -v -ra tests/test_browser_live.py -k codex_existing --junitxml=check-logs/codex.xml
```

The uploaded artifact `12614686644` was retrieved and extracted under
`/tmp/bridge-window-validation-20261025/codex-preflight-f9eaacd/`.
`codex.exit`, `codex.log`, `codex.xml`, `source-revision.txt`,
`uncommitted-inputs.txt`, and `environment.txt` retain the result and environment.
No uncommitted source input was reported by the runner.

Earlier full run [40231068252](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40231068252)
at source `7baa9e2706a8cd87c3be5a5b0e0b6e6d26d2b6bc` returned
515 passed, 23 failed, 1 skipped, 26 warnings in 292.05 seconds.
The failures were 22 new Codex fixture navigation cases and the built-UI target
selector. The fixture navigation failures are covered by the later 23 passing
cases; the UI selector was corrected, but final full-suite acceptance has not
been collected. The opt-in skip requires a separate disposable Voice server.
The same earlier run passed the real packaged noVNC-to-x11vnc direct and unified
account-popup smoke tests. Their durations in the collected JUnit report were
2.484 and 2.825 seconds, respectively. This is synthetic browser acceptance,
not real-account acceptance. Evidence is retained under
`/tmp/bridge-window-validation-20261025/check-7baa9e2/`.

## Outstanding full regression and builds

The latest full-suite run remained in the browser acceptance step beyond its
intended command timeout when checked. Its original timeout wrapped pytest but
not the following log pipe, leaving the pipe outside that deadline. The workflow
now wraps the complete pipeline and has an independent step deadline. This fixes
a supervision gap; the actual long-wait location is not established without the
final log. Final full pytest success, final built-UI end-to-end success, and final
app/worker image build success remain **unverified**. Do not infer them from the
targeted suite. Production remains on the previously deployed application.

## Cache changes

Checks now caches uv downloads, Playwright browser binaries and target-scoped
BuildKit layers, alongside the existing npm download cache. Playwright binaries
are saved immediately after installation so later test failure does not discard
the download. Docker source copies follow heavyweight worker dependencies to
preserve reusable layers. Image jobs depend on successful validation; workflows
cancel superseded runs by ref. Browser installation and test pipelines have
bounded deadlines. The first cache fill still downloads dependencies; a later
cache hit is not claimed without observing it. Credentials, databases and browser
session/device archives are excluded from these cache paths.

## Collected deployment acceptance (2026-10-26 UTC)

Hosted deployment run [40247131930](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40247131930)
succeeded at source `dec10de4a5c7a1162fffdcea20a325f5c938c3a2`.
This supersedes the outstanding deployment status above. The final artifact
pipeline separates non-browser validation from selected headed acceptance;
it does not claim a final complete pytest run. Collected validation contains
459 passed and one opt-in skip, with 48 frontend tests passed and a successful
production frontend build. Selected browser/device, Codex continuation,
monitor and packaged noVNC acceptance contains 46 passed and 30 deselected.
Both recorded validation exits and the native ARM64 image export exit are 0.
No uncommitted runner input was reported.

Artifacts are validation `12618874028`, browser `12618884317`, and ARM64 images
`12618967953`. The downloaded image archive SHA-256 is
`e7ce24712e35996ca48eca1668283a3cfe71d94057f05a0aaae70ac941995ba7`,
matching its hosted checksum manifest. Evidence, exact commands, logs, exits,
archive configuration and identity audit are retained in the restricted directory
`/tmp/bridge-account-window-deploy-20261025/` on the deployment controller.

`docker load -i images.tar.gz` succeeded. Hosted image identities and archive
configuration blob hashes are app
`9ba66bedee002b1f2970646e0d35587736904765c3962ca8ccfdf8f86cadf859`
and worker
`4129cc3d352352f287a929480139627f422702402a5a1ac7ed337cffd908e859`.
The deployment daemon reports different loaded image IDs: app
`sha256:c62175a06be29350b4024acb8faa9d7f28dbeb30107ea4d070123bd27e7526f5`
and worker
`sha256:63cd9c9d9f7c8ca9d756e8c6b7e7c0b53db16cc00354d21e5a81d054413a8ab1`.
The audit verifies that each loaded image's configuration and complete ordered
root filesystem layer diff IDs exactly match its corresponding archive entry;
both retain ARM64 architecture and the exact source revision label. The reason
for the daemon's differing identity representation was not established.

Immediately before replacement, the authenticated task metadata contained no
active task. Scheduled maintenance was temporarily disabled and both services
were stopped. Using the retained Compose environment, volume and master key,
the offline command was:

```sh
docker compose run --rm --no-deps --pull never app python -m app.cli migrate
docker compose up -d --no-build --pull never --wait app worker
```

Migration and startup both exited 0. Schema version is now 4. Maintenance was
restored to its prior enabled state and the administrator session was logged out.
No backup, database copy or rollback tag was created. No account credentials or
browser state were inspected, and no real-account login was performed.

The deployed app container is
`165b6018aa2e658a159df5a37ec0364c2e20866816028b06ef913c8f49627c86`;
the worker is
`58eed18efc4593d62edc66b9c0e398066075f8c1b10bb06d705efbf0b4b53263`.
Both are healthy; `/readyz` returned HTTP 200. All 20 Python source files in
each service match the reviewed source, including `rfb_monitor.py`. All three
served frontend files match installed artifact bytes. Existing data mounts and
both Compose networks are retained. The separate Voice gateway's container ID,
image, start time and network metadata match their pre-deployment values exactly.
Main-agent independent acceptance also verified worker/browser availability,
maintenance restoration, the new frontend action labels and preserved successful
task metadata. Real-account acceptance of the new window/continuation capabilities
remains **unverified**.
