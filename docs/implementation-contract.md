# Implementation contract

This document freezes the initial implementation boundary. All integrations remain unverified until real service acceptance.

## HTTP

All business endpoints use `/api/v1`, an HttpOnly `bridge_session` cookie, and `X-CSRF-Token` on mutations. `POST /auth/login` accepts `{password}` and returns `{csrf_token}`; `GET /auth/session` returns the same. `POST /auth/logout`; `POST /auth/password` accepts `{current_password,new_password}`. Errors use `{detail: safe English message}`.

`GET /accounts`, `/targets`, `/tasks` return objects keyed by the plural resource. Account public fields: id, username, status, route_type (unset/direct/proxy), version, target_ids, has_password, has_totp, has_mailbox, created_at, updated_at. POST /accounts accepts username,password,totp?,mailbox_url?,allow_http_mailbox?,route_type?,proxy?,target_ids?. PATCH /accounts/{id} accepts the same optional fields; explicit null clears optional secrets, omitted preserves. proxy is `{server,username?,password?}`. DELETE resources returns `{deleted:true}`. Import preview/confirm accept `{text}`; preview returns `{records:[{line,account?,valid,duplicate?,error?}]}`, confirm `{imported:[username]}`.

Target POST/PATCH accepts `{kind,name,config}`; kinds `cliproxyapi`, `chatgpt-web-voice`. Config: base_url, management_key (CPA) or admin_username/admin_password (voice), optional allow_http. Public fields exclude config secrets and include verification (`unverified`). POST /targets/{id}/test performs a connection test.

POST /accounts/{id}/tasks accepts `{target_id,idempotency_key?}`. GET /tasks/{id} returns public task, GET /tasks/{id}/events streams SSE `id`, `event: task`, `data: {id,state,phase,message}`; Last-Event-ID resumes. POST task actions: /cancel, /takeover, /continue, /code `{code,submission_id}`, /retry-sync. GET /runtime returns worker_alive,browser_available,maintenance_enabled,version. PATCH /settings accepts maintenance_enabled and retention_days. GET /settings returns those. GET /tasks/{id}/takeover is authenticated WebSocket (same-origin).

## Worker and adapters

Main owns app/config.py, crypto.py, db.py, main.py, models.py, queue.py, worker.py, cli.py and API tests. Browser agent owns app/browser.py, app/routing.py, app/mailbox.py, app/totp.py, tests/test_browser*.py and tests/test_routing*.py. Integration agent owns app/integrations.py, tests/test_integrations.py. UI agent owns frontend/, Dockerfile, docker-compose.yml, .dockerignore, .github/, docs/deployment.md. Other docs remain main-owned.

Browser entrypoint: `run_login(account: dict, target: dict, control, saved_state: dict | None = None) -> dict`. Account has decrypted username,password,totp,mailbox_url,allow_http_mailbox,route_type,proxy. Target has kind and config. control exposes `phase(name,message)`, `checkpoint()` (raises on cancellation/lease loss), `wait_human(reason, *, phase="waiting_human") -> str | None` (code or continuation), `save_state(dict)`. Browser result is `{credential_type:'codex_oauth'|'chatgpt_web',credential:dict,expires_at:float|None,identity:str}`. Exceptions safe fixed messages only; no secrets. Optional control `browser_ready(port)` and `browser_closed()` support takeover. Blocking sync Playwright allowed. Same worker owns global browser file lock.

Integration entrypoint: `sync_credential(target: dict, result: dict, account: dict, remote_id: str | None = None) -> dict` returns `{remote_id,verified:bool}`. `test_connection(target: dict) -> dict` returns `{reachable,verification:'unverified'}`. target includes kind,config; account includes username,route_type,proxy. Never infer direct from an empty downstream proxy. Unknown downstream contracts fail closed with actionable safe exception. No fabricated successful verification.

Persisted task states: queued,running,waiting_human,sync_pending,succeeded,failed,cancelled,interrupted. Config versions freeze at enqueue; edits before claim interrupt task. Browser credential result encrypted; sync_pending frees browser. Main performs only serial credential verification.

## Integrated amendments

- GET /tasks/{id}/history returns `{events}` with persisted event_id, task id in `id`, state, phase, message, takeover_available, created_at. SSE uses the same data and its own monotonic wire id.
- Task detail adds account_username; public task records include remote_id for reconciliation audit.
- POST /tasks/{id}/discard-sync accepts `{confirmation: exact account username}` for an idle pending sync. It deletes local pending material after explicit operator confirmation, retains remote ID/audit, marks interrupted/remote_outcome_unknown and account sync_unknown, and never deletes a downstream account. Ordinary cancellation conflicts after a possible remote write.
- A pending target may update administrator credentials/name while preserving base_url, allow_http, kind and compatibility; retry uses the corrected target version without repeating login.
- Target config `compatibility` accepts cpa-auth-files-v1 (CPA default) or explicitly selected bridge-v1 (voice). The voice client requires that server contract and is not native gateway support.
- Account optional nested proxy secrets preserve omitted fields; explicit null clears an optional secret. Current account/target identity/route cannot change during pending synchronization.
- `maintenance_enabled` enables automatic saved-session maintenance and never pauses manual task admission.

### Manual input phases

A `waiting_human` task uses durable `phase` values to describe supported actions. `email_code_required` and `authenticator_code_required` expose code entry; `/code` returns 409 for every other waiting phase. `password_required` means the password form remained after its single automatic submission and requires browser review; `waiting_human` means general manual review/takeover. Continue and takeover remain available for all waiting phases. The `/code` request shape is unchanged, including submission idempotency. Older tasks with only `waiting_human` require takeover/continue to re-identify the page before code entry becomes available. Deploy worker and UI together. A submitted code is applied only if the current page still matches the code challenge that requested it.
