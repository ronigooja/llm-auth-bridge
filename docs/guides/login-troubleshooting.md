# Login troubleshooting

This guide applies when a ChatGPT web login task enters `login_failed` or
`browser_review`, especially after the provider login control or email form was
submitted.

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

