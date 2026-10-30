# Data and task lifecycle

## Durable model

[db.py](../../app/db.py) owns the schema and versioned transactional migrations.
The current database schema is **v6**. Connections enable foreign keys and a
ten-second busy timeout; initialization/migration configures SQLite WAL. App and
worker validate the schema and key at startup and never migrate concurrently.
The explicit CLI migration preserves existing records, including case-distinct
legacy identities; new operations reject case-insensitive duplicates.

| Data | Role |
| --- | --- |
| `accounts`, `targets`, `account_targets` | Versioned account configuration, downstream configuration and associations |
| `tasks`, `task_events` | Frozen execution references, ownership, progress and transactional event history |
| `pending_credentials`, `syncs` | Encrypted pre-handoff results and durable downstream verification state |
| `browser_profiles`, `browser_devices`, `browser_sessions` | Account preferences, encrypted native devices and saved session state |
| `native_sessions` | Encrypted downstream OAuth session references and callback submission markers |
| `login_flows`, `browser_requests` | Login-flow dependencies and browser request idempotency |
| `admin`, `sessions`, `login_attempts`, `runtime`, `settings` | Administrator access, runtime health and maintenance policy |

Schema v2 introduced profiles and native sessions, v3 added device archives, v4
added dependent login flows and browser request tracking, v5 added web-session
health, and v6 added the `unavailable` web-session status. The migration source is authoritative for columns, constraints and legacy
conversion details. Profile format and database schema have independent version
lifecycles; the current profile representation is described in [runtime](runtime.md).

## Ownership and scheduling

The usual authorization path is `queued → running → waiting_human → running →
sync_pending → succeeded`. Human waiting is optional. `failed`, `cancelled` and
`interrupted` are terminal outcomes; `phase` refines progress without creating
another state machine. Browser-window tasks close without downstream sync.

Enqueue freezes account and target versions. Claiming uses `BEGIN IMMEDIATE`,
checks prerequisites and versions, and issues a random execution ID and lease.
Owned mutations check that execution ID and a live lease. The shared process file
lock complements database fencing and serializes the whole task, including human
waits and synchronization. A separate heartbeat thread renews task ownership and
worker liveness independently of browser actions. This requires one shared lock
on one host; see [ADR 003](decisions/003-execution-and-handoff.md).

Ready synchronization retries are claimed before new queued work. Among eligible
queued tasks, manual login has priority. A dependent login task becomes eligible
only when its prerequisite succeeds with verified phase; a failed, cancelled or
interrupted prerequisite interrupts its queued child. Request idempotency and
active-task checks prevent duplicate work. Exact creation and action semantics
belong to the [HTTP contract](../contracts/http-api.md).

Browser operations use bounded checkpoints for cancellation, lease loss,
shutdown and the active deadline. The default active budget is ten minutes;
human waiting has a separate thirty-minute budget. Resuming extends the active
deadline by the time spent waiting and rechecks the existing page. Input commands
are encrypted and submission IDs make retries idempotent. Takeover transport and
same-browser behavior belong to the [account window contract](../contracts/account-window.md).

## Credential handoff and cancellation

For auth-files and Voice compatibility flows, the worker saves an encrypted
result into `pending_credentials`. Browser teardown finishes before another task
is claimed. Synchronization failures retain that result, allowing retries without
another browser login.

Immediately before a downstream write, one transaction checks cancellation and
increments the durable attempt counter. After a write may have started, ordinary
cancellation is rejected because the remote outcome can be unknown. A retry
reconciles first; it must not overwrite a mismatched, potentially rotated CPA
credential. An adapter may clear uncertainty only when it explicitly establishes
that no write was possible. Adapter responsibilities and result shapes belong
to the [worker contract](../contracts/worker-adapters.md).

An administrator can confirm the account identity to discard an idle pending
result. This removes local credential material, preserves remote ID and audit,
and records an unresolved outcome requiring remote reconciliation. It does not
delete a downstream account. Successful verified handoff removes the bridge's
active pending credential copy; downstream owns later CPA refresh rotation.

Native CPA authorization moves PKCE, exchange and staging to the downstream
extension. The bridge persists its encrypted native-session reference and marks
callback submission before sending it. Staging is distinct from installing a
usable credential. Commit enters the same fenced `sync_pending` write boundary;
readback must confirm identity, explicit route, stable remote ID and persisted
credential digest. See the [CPA protocol](../contracts/integrations/cliproxyapi.md).

## Recovery and mutation boundaries

Expired ordinary browser execution is interrupted, requiring a new authorization;
authorization codes are never automatically replayed. Expired synchronization
ownership releases the task for reconciliation. Native sessions instead queue
recovery so the worker can inspect downstream state; an uncertain callback or
exchange is polled rather than resubmitted. Unresolved native recovery and
cancellation remain explicitly retryable, preserving the native reference.

Version checks prevent an old task from silently using changed configuration.
Browser-active resources cannot be edited. Idle synchronization allows limited
target name/management-secret repair while retaining destination, kind and
compatibility binding. Active native references preserve account and target
binding during recovery, cancellation and pending commit. Permitted repairs
atomically update the frozen target version. Terminal remnants do not lock
resources. Exact conflict responses belong to the
[HTTP contract](../contracts/http-api.md); local resource deletion never deletes
remote accounts.

## Events and maintenance

State changes append events in the same transaction. SSE uses monotonic event
IDs, `Last-Event-ID` replay, periodic session checks and disabled proxy buffering.
Authenticated history allows refresh recovery. The frontend stores navigation
and selected task in its URL hash. See [main.py](../../app/main.py) and
[queue.py](../../app/queue.py) for event publication and replay.

The worker scans for due Voice maintenance every fifteen minutes using the saved
web session; it does not resubmit the password. After verified handoff, the next
check is scheduled at the earlier of six hours later or one hour before known
expiry. Unknown expiry and transient retry use six-hour checks. Invalid sessions require reauthorization. `maintenance_enabled` controls
automatic maintenance, not manual task admission. CPA refresh remains downstream
owned. See [worker.py](../../app/worker.py) and the
[Voice integration](../contracts/integrations/voice.md).

Retention deletes final task records and their cascading events after the
configured interval, preserving parents needed by active dependent tasks.
Pending synchronization is not a terminal state and is retained. Expired
administrator sessions are also removed. Operational backup and migration steps
belong to the [deployment guide](../guides/deployment.md).

### Web session health

`web_session_health` stores the latest account-level browser check independently from each target's `syncs` row. A migrated database starts with no health record, which is exposed as `unknown`; historical `ready` values are not used as evidence. Checks are fenced by the task execution lease and persist `valid`, `signed_out`, `error`, or `unavailable` (provider rejection) with timestamps and a safe error code before downstream synchronization begins.
