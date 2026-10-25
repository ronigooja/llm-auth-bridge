# Browser identity consistency review

## Scope and conclusion

Two independent read-only sub-agent reviews examined revision
`777de617e52b479a603bf13226e736a042cc3611` on 2026-10-25. Both used
`gpt-6.1-sol` at medium effort, as required by the working agreement. The main
operator checked their source references and consolidated the findings below.
No reviewer accessed credentials, account databases, browser storage, or sensitive
screenshots. No real-account login, browser launch, build, or executable test was
performed for this review. No application configuration or implementation was
changed.

The implementation preserves account-scoped browser options and selected session
state. It does not establish a complete persistent device identity, distinct
hardware fingerprints across accounts, or equivalence to an ordinary interactive
browser. Static review found a concrete display configuration inconsistency and
several coverage limits. None establishes that the observed provider login
failure was caused by fingerprinting.

## Findings

### P2: generated geometry is not coordinated with the real display

`app/browser_identity.py:15-16,31-40` generates viewport sizes from
1200–1919 by 700–1199 and declares screen height as viewport height plus 80.
`Dockerfile:56` starts a fixed 1440 by 900 Xvfb desktop. Some generated viewport
and screen dimensions exceed that desktop. There is no corresponding display
resize or production geometry check.

This is a code-proven configuration divergence. The exact relationship among
JavaScript inner/outer window sizes, screen/available dimensions and actual VNC
visibility remains unmeasured. Do not infer a specific impossible browser-visible
combination or provider detection result from the configuration alone.

Recommendation: coordinate supported geometry with the actual display and verify
both browser-visible values and takeover visibility in a headed synthetic
acceptance job using the production runtime.

### P2: account state restoration is narrower than persistent browser reuse

`app/browser.py:370-388` launches a fresh Chromium and browser context per task.
`app/browser.py:294-296` saves default `context.storage_state()`. This preserves
cookies and localStorage, but does not opt into IndexedDB capture and does not
preserve sessionStorage, disk cache or a complete browser profile.
`app/worker.py:176-213` correctly loads the same profile and saved state by account
for Voice and Codex tasks. That sharing is real; the recovered state is partial.
Whether any omitted state matters to the provider is unverified.

Recommendation: describe the supported persistence contract precisely. Use a
synthetic site to verify cross-task cookie and storage restoration. Expand the
persistence scope only when an actual compatibility requirement is demonstrated,
while preserving encryption and cancellation/lease boundaries.

### P2: recent state can be lost on unsuccessful navigation

The adapter saves state on success and before its manual pause, but the
Playwright/HTTP/JSON error path at `app/browser.py:595-604` closes the browser
without saving recent changes. Cookies received shortly before a subsequent
failure can therefore be absent on the next task. This is a state continuity
risk, not proof of a fingerprint change or of the observed provider failure.

Recommendation: consider safe state checkpoints at successful navigation
boundaries. Any added checkpoint must respect task ownership, cancellation and
identity validation, and must not replace the original error with a save error.

### P2: current tests do not measure production browser consistency

`tests/test_browser_identity.py:27-41` checks generated dictionaries and later
tests verify encrypted account-level stability. `tests/test_browser.py` checks
mock launch/context arguments. `tests/test_browser_live.py:58-67` uses headless
Chromium, optionally a system executable, with sandbox behavior dependent on UID.
Production uses bundled headed Chromium with sandboxing in Xvfb.

These are useful tests of their stated contracts, but they do not establish
production display geometry, UA/client-hint coherence, graphics/font properties,
or complete Web-to-Codex session reuse.

Recommendation: add a GitHub-hosted synthetic headed measurement job using the
production image and sandbox configuration. Whitelist browser version, UA/client
hints, window/screen geometry, DPR, language/timezone and basic graphics/font
availability. Use a neutral synthetic origin and fresh synthetic state; do not
collect real account storage, environment secrets, traces, HAR or recordings.

## Additional boundaries and positive findings

- `identity_seed` is stored in the encrypted profile but is deliberately excluded
  from `context_options()`. It does not alter browser-observable device signals.
  Per-account differences mainly consist of viewport/screen choices; other
  configured preferences are shared. Distinct dimensions do not prove distinct
  hardware identities.
- The project retains bundled Chromium's native user agent. The API and browser
  install use the same pinned Playwright 1.56.0 version. No source-level fabricated
  UA/client-hint disagreement was found. Browser upgrades may still change
  browser-observable properties.
- Headed mode does not remove normal Playwright automation behavior. The pinned
  [Playwright Chromium launch switches](https://github.com/microsoft/playwright/blob/v1.56.0/packages/playwright-core/src/server/chromium/chromiumSwitches.ts#L84)
  include `--enable-automation` in the default mode. The project does not override
  default launch arguments. Exact runtime flags and JavaScript properties were
  not measured in this review. This is an automation environment by design;
  adding JavaScript stealth patches is not a consistency fix.
- All accounts share the worker image, Chromium installation and virtual display.
  Canvas, WebGL, font, audio and hardware isolation are not implemented. The lack
  of a GPU device mapping alone does not prove a particular graphics renderer.
- `en-US` and UTC are fixed account preferences and do not follow proxy edits.
  These can be legitimate user preferences. A different IP region is not, by
  itself, proof of a contradictory fingerprint.
- Blocking service workers, installing request routing and restricting WebRTC
  change ordinary browser functionality. Their effects should be checked through
  functional compatibility acceptance, while preserving the route isolation
  requirements. Do not automatically remove these safeguards based on a login
  error.
- Browser navigation and server-side token exchange use the configured account
  route, but Chromium, Playwright's API request context and httpx are different
  HTTP clients. Cookie sharing does not imply identical request headers or TLS
  behavior. Such differences are not inherently OAuth defects.

## Validation and next decision

The review is static-only; no new pytest result is claimed. Existing hosted
validation of the unchanged application source reported 251 passed and one
skipped at [run 40220196006](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40220196006).
That result does not supply the missing browser identity measurements.

Prioritize production geometry measurement and session persistence verification
before attributing the login error to device identity or changing account
fingerprints. Keep any later real-account verification serial and use the
project's existing account profile and route.
