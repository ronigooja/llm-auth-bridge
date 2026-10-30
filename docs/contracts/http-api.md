# HTTP API

[Request models](../../app/models.py) and [route implementations](../../app/main.py)
are the executable source. All paths below are relative to `/api/v1`. Business
requests use the HttpOnly `bridge_session` cookie; mutations other than login
require same-origin validation and `X-CSRF-Token`. Errors expose safe `detail`
messages; validation omits input values. Authentication behavior is described in
[the product guide](../product/authentication.md).

## Administrator session

| Method and path | Body / response |
| --- | --- |
| `POST /auth/login` | `{password}` → `{csrf_token}` |
| `GET /auth/session` | `{csrf_token}` |
| `POST /auth/logout` | Revokes current session |
| `POST /auth/password` | `{current_password,new_password}`; revokes all sessions |

## Accounts and import

`GET /accounts` returns `{accounts}`. Public fields include `id`, `username`,
`status`, `route_type` (`unset`, `direct`, `proxy`), `version`, `target_ids`,
`has_password`, `has_totp`, `has_mailbox`, `allow_http_mailbox`, and timestamps.
`POST /accounts` requires `{username,password}` and accepts `totp`, `mailbox_url`,
`allow_http_mailbox`, `route_type`, `proxy`, and `target_ids`. `PATCH /accounts/{id}`
accepts those optional fields. Omission preserves saved fields; explicit null
clears optional secrets. Nested proxy secrets follow the same preservation rule.
Proxy input is `{server,username?,password?}` with a required port and `http`,
`https`, `socks5`, or `socks5h` server scheme; embedded user information is rejected.
Masked placeholder values cannot replace secrets.

`GET /accounts/{id}/secrets` is an authenticated administrator edit action that
returns saved password, TOTP, mailbox URL and proxy; ordinary account views omit
those values. `DELETE /accounts/{id}` returns `{deleted:true}` and rejects active
work. Local deletion never deletes downstream accounts.

`POST /import/preview` and `POST /import/confirm` accept `{text}`. Preview returns
`{records:[{line,account?,valid,duplicate?,error?}]}`. Confirmation atomically returns
`{imported:[username]}` or rejects the import.

`GET /accounts/{id}/browser-identity` returns `{platform:"windows"|"macos"}` without
allocating an unused profile. `PUT` accepts exactly that field and rejects any
queued, running, waiting or pending-sync task with 409; unsupported platforms or
extra fields return 422. Changes preserve seeds, credentials, proxy, sessions and
device archive. [Runtime](../architecture/runtime.md) defines coverage and profile
format upgrades. There is no UI platform selector.

## Targets

`GET /targets` returns `{targets}`. `POST /targets` and `PATCH /targets/{id}` use
`{kind,name,config}` (PATCH fields may be omitted). Kinds are `cliproxyapi` and
`chatgpt-web-voice`. Configuration requires `base_url`, plus `management_key` for
CPA or `admin_username`/`admin_password` for Voice; `allow_http` and `compatibility`
control transport and protocol. Public config includes only safe URL/compatibility
settings, alongside `id`, `kind`, `name`, `version`, `verification`, and `created_at`.
`POST /targets/{id}/test` checks management reachability, not provider usability.
`DELETE /targets/{id}` rejects active work and returns `{deleted:true}`.

New CPA targets default to native OAuth; explicit null keeps legacy auth-files
behavior, and edits preserve the saved protocol. Voice requires explicit
`bridge-v1`. Refer to the [CPA](integrations/cliproxyapi.md) and
[Voice](integrations/voice.md) contracts for compatibility and configuration.

Browser-active resources cannot be edited. During idle non-native pending sync,
only target administrator secrets/name may change while the endpoint, kind and
protocol remain bound. Persisted active native sessions also block account and
target-binding mutations in queued recovery/cancellation. Idle native recovery or
pending sync allows only management-key/name repair at the same binding, updating
the frozen target version atomically. Worker-owned tasks reject that repair;
terminal native session remnants do not keep resources locked.

## Task creation

`POST /accounts/{id}/tasks` accepts `{target_id,idempotency_key?}` for an existing
bound target. `POST /accounts/{id}/login-flow` accepts
`{voice_target_id,cli_target_id?,idempotency_key?}`. Voice is required; omitted/null
CLI returns `{tasks:[voice]}`, otherwise `{tasks:[voice,cli]}`. Both targets must
have the correct kind, be bound to the account, and have an explicit route.
Validation and task insertion are atomic. Reusing a key with different inputs,
including adding/removing CLI, conflicts. Public tasks expose nullable
`depends_on_task_id`. CLI becomes eligible only after its Voice prerequisite has
succeeded with phase `verified`; pending sync never releases it. Failed, cancelled,
interrupted or missing prerequisites interrupt the dependent task.

`POST /accounts/{id}/browser` accepts optional `{idempotency_key?}` and returns
`{task}`. It reuses live same-account or eligible queued work, otherwise creates a
target-free `browser_window` task. A dependency-blocked CLI task is ineligible.
Idle synchronization does not block opening a device; the global worker lock
still serializes browsers. Continue closes and saves a window without credential
extraction or sync; cancellation also preserves the device while its lease is
owned. See [account operations](../guides/account-workflow.md).

## Task actions and events

`GET /tasks` returns `{tasks}`; `GET /tasks/{id}` returns a public task including
`account_username`, `remote_id` and dependency metadata. Native session material
is excluded. Task POST actions are `/cancel`, `/takeover`, `/continue`, `/retry-sync`,
`/code` with `{code,submission_id}`, and `/discard-sync` with `{confirmation:
exact account username}`. Submission IDs make code delivery idempotent. Request
keys and submission IDs are 8–128 characters; the UI uses `crypto.getRandomValues`
for trusted HTTP origins as well as HTTPS.

A waiting task accepts code only in `email_code_required`,
`authenticator_code_required`, or `verification_code_required`; other phases
return 409. The last phase accepts manually supplied SMS/ambiguous codes and never
initiates automatic TOTP or mailbox retrieval. `password_required` means the
single password submission needs browser review; `waiting_human` means general
review. `account_deleted`, `account_deactivated`, `account_suspended`, and
`account_rejected` mean the provider displayed an explicit account rejection
page (matched by its wording, provider error parameters, or an authentication
error path, including after an aborted navigation); the browser remains
available for takeover so the operator can inspect it, and the account's
`web_session.error_code` records the code as soon as the pause starts.
`browser_review` means no known page or rejection was recognized. A later
account window is a new browser session and cannot reproduce a rejection page.
Continue/takeover remain available in all waiting phases. Older generic
waiting tasks need page re-identification before code entry. Code is applied only
to the still-matching challenge. Deploy worker and UI together.

Ordinary cancellation conflicts once a remote write may have started. For idle
pending sync, confirmed discard deletes local pending material, retains remote
ID/audit, marks task `interrupted`/`remote_outcome_unknown` and account `sync_unknown`,
and never deletes the remote account. Retry reconciles uncertain writes rather
than blindly replacing credentials. Native queued `native_recovery_failed` and
`native_cancel_pending` phases expose `/retry-sync` for reconciliation; ordinary
cancellation remains available before commit.

`GET /tasks/{id}/history` returns `{events}` ordered by persisted `event_id`.
`GET /tasks/{id}/events` streams SSE with a monotonic wire `id`, `event: task`, and
`data: {id,event_id,state,phase,message,takeover_available,created_at}`; data `id`
is the task ID. `Last-Event-ID` takes precedence over the `after` query cursor.
Streams check the session periodically, send heartbeat comments and disable proxy
buffering. WebSocket endpoints are defined in the [account window contract](account-window.md).

## Runtime and settings

`GET /runtime` returns `worker_alive`, `browser_available`, `maintenance_enabled`,
and `version`. `GET /settings` returns `maintenance_enabled` and `retention_days`;
`PATCH /settings` accepts either. Retention is 1–3650 days. Maintenance enables
automatic saved-session renewal and does not pause manual task admission.

Outside the API prefix, `/healthz` provides liveness and `/readyz` validates the
initialized database/key. Authenticated `/account-window`, `/account-viewer`,
`/account-viewer.js` and noVNC assets support the account popup; they do not grant
unauthenticated browser access.

### Web session health and maintenance summaries

Account responses include a `web_session` object with `status` (`unknown`, `valid`, `signed_out`, or `error`), `checked_at`, `last_success_at`, and a safe `error_code`. Provider rejection codes include `account_deleted`, `account_deactivated`, `account_suspended`, and `account_rejected`. The value is written only after a leased web session check or a provider rejection pause in any login task; account creation and downstream synchronization do not imply a valid web session. `target_syncs` contains the bound target kind, synchronization state, verification time, maintenance plan (`next_check`), pause reason, and active task ID. Credentials are never returned.

Task `kind` identifies the operation (`maintenance`, `login`, or `browser_window`). Its `phase` distinguishes web-session checking from downstream synchronization. A task is shown as checking only while its execution lease is valid; queued maintenance is reported as waiting for a check. `next_check` describes scheduling and does not determine session validity.
