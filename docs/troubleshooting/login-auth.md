# Login troubleshooting

This guide applies when a ChatGPT web login task enters `login_failed` or
`browser_review`, especially after the provider login control or email form was
submitted, or when an account proxy is configured.

## Meaning of the task phases

- `login` means the ChatGPT home page login control was found and dispatched.
- `email` means the configured account email was filled and the provider form
  submit was dispatched.
- `browser_review` means the current page was not classified as a supported
  login, challenge, consent, account chooser, or explicit provider rejection
  page before the transition deadline elapsed.
- `account_deleted`, `account_deactivated`, and `account_suspended` are emitted
  only when the provider rejection classifier finds an explicit supported
  rejection signal.

`browser_review` is therefore a classification result, not proof that the
account was rejected. The operator must inspect the live account browser or
cancel the task.

## How to use this guide

Apply these steps to each failed login task:

1. Read the task's final `phase`, `message`, and event history before opening
   the account browser.
2. If the phase is `route_timezone`, investigate the account route and proxy
   preflight first. The provider browser was not reached, so browser takeover
   cannot provide evidence for that task.
3. If the phase is `browser_review` or `waiting_human`, take over the browser
   for that same task and inspect the current foreground page. Continue the
   task only after confirming the next provider step; otherwise cancel it.
4. If the phase is `account_deleted`, `account_deactivated`, or
   `account_suspended`, record the explicit provider rejection and stop using
   that account.
5. For any other `login_failed`, preserve the task id and phase, reproduce with
   a new task, and compare the event sequence. Do not infer a provider
   rejection from the generic message alone.

This guide supports diagnosis and operator decisions; it does not replace the
task state shown by the application or authorize submitting credentials to a
different route.

## Incident history: saved account acceptance

The saved account acceptance runs for account id 4 and target id 2 showed this
sequence:

| Tasks | Observed sequence | Interpretation |
| --- | --- | --- |
| 60, 63–66 | `login` then `login_failed` | The login control path failed before the next page could be classified. |
| 67 | `login` → `email` → `browser_review` | The login-control failure was fixed; the post-email page remained unclassified. |
| 68 | `login` → `email` → `browser_review` | The same post-email classification gap reproduced after deployment. |

Task 67 was run on commit `82b92e7` and task 68 on the same deployed revision.
Both tasks were cancelled after evidence collection. No credentials, cookies,
page body, screenshots, or browser traces were retained.

## Proxy route preflight failures

This section applies when a proxy-routed task fails in the `route_timezone`
phase before any browser page is opened. The timezone lookup uses the account
route to query a public geolocation service. An unavailable geolocation
service, proxy DNS failure, or proxy socket error must not be reported as a
provider login failure when the configured route may still reach OpenAI.

Task 75 reproduced this failure: it ended in `login_failed` after two
`route_timezone` events and never created a takeover page. Commits `477c21f`
and `9288cd3` changed this behavior. The worker now retains the account's last
verified timezone when the lookup fails, and normalizes low-level socket
errors to the safe `RouteError` type. The browser then exercises the real route
so an explicit provider rejection can be classified and observed.

Tasks 76 and 77 showed that this phase can also fail after the route lookup,
while the task event still reports only `route_timezone`. A production-side
diagnostic for account 4 independently started the configured route, received
HTTP 200 from the geolocation endpoint, and resolved `Asia/Tokyo`; the stored
browser profile was version 4 with a valid timezone field. This rules out a
general DNS, proxy-authentication, or socket-connectivity failure for that
check. Commit `09539ec` therefore treats timezone preference persistence as
auxiliary as well: cancellation and lease-loss errors still stop the task, but
an ordinary persistence/runtime error must not prevent the provider browser
from opening.

For this incident, inspect task events first. If the final phase is
`route_timezone`, the provider page was not reached; do not ask the operator to
inspect a browser window. After deployment, create a new task and verify that
the phase progresses to `login`, `email`, or an explicit provider rejection.

## Relevant historical fixes

The following commits address separate failure layers and must not be treated
as proof that the complete provider flow is accepted:

- `3e8621e` added explicit provider rejection classification.
- `36094c0` changed unknown pages to the `browser_review` phase.
- `563f1ce` preserved the browser for navigation failures and takeover.
- `80835ca` and `dd1e8c5` saved the provider review URL for browser reopening.
- `e349671` removed a redundant `/auth/login` navigation.
- `8eed804`, `296c9fa`, and `f1a7070` made provider clicks tolerant of document
  replacement and redirect timing.
- `c114b2d` broadened detection of the current ChatGPT login controls.
- `82b92e7` stopped the Playwright login locator from overwriting the task
  control object and added bounded navigation diagnostics.

The remaining known gap is the page observed after email submission. The
current saved browser state contains cookies/origins and a review URL, but not
the page DOM or screenshot, so a later task cannot reconstruct that page from
the archive.

## Required next investigation

When the email-to-`browser_review` transition reproduces, diagnostics may record
only:

1. the provider host and URL path, excluding query strings and fragments;
2. the detected state and task phase;
3. the exception class, if a browser action failed;
4. safe structural facts such as supported input/control kinds and document
   readiness.

Do not record account credentials, cookies, access tokens, page body text,
screenshots, HAR files, video, or full provider URLs containing query values.
Add a synthetic fixture for the observed page classification before changing
selectors, then repeat a serial real-account run and record its task phases.

