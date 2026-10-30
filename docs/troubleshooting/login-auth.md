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

`browser_review` is a classification result, not proof of provider rejection.
Only an explicit supported rejection signal establishes that conclusion.

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

Historical observations and fixes are preserved in the [login incident
archive](../archive/login-auth-incidents.md); they are not current acceptance
evidence.

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
