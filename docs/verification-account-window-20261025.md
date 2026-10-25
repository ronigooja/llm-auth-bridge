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
