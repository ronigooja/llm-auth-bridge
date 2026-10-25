# Account login flow and browser window

`POST /api/v1/accounts/{account_id}/login-flow` accepts
`{voice_target_id, cli_target_id, idempotency_key?}` and returns `{tasks: [voice, cli]}`.
Both targets must exist, have exactly the respective `chatgpt-web-voice` and
`cliproxyapi` kinds, and be bound to an account with a selected route. Creation
validates and inserts both tasks in one transaction. The optional key identifies
the complete request; reusing it with different inputs returns a conflict.

Public tasks include nullable `depends_on_task_id`. CLI stays queued until the
voice task succeeds with phase `verified`, after downstream synchronization has
been verified. A pending or failed synchronization waits for explicit retry or
resolution; it does not release CLI. Failed, cancelled, interrupted or missing
prerequisites interrupt the blocked task. Recovery preserves this ordering after
worker restart. Existing per-target task creation remains available.

`POST /api/v1/accounts/{account_id}/browser` accepts an optional
`{idempotency_key?}` and returns `{task}`. It returns a live same-account task or
an eligible queued task. Otherwise it creates a `browser_window` task with no
target. A CLI task blocked on an incomplete prerequisite does not count as an
eligible browser. An idle synchronization does not prevent a browser window.
The shared worker lock still serializes every browser across accounts.

Browser windows reopen that account's saved device and proxy at ChatGPT. Continue
closes the window and saves it; cancellation also preserves the device through
the browser adapter. Closing succeeds without extracting credentials or syncing
a target. Account windows and login tasks use the same takeover transport.
Real-account browser reopening and ordered authorization remain **unverified**.

Schema v4 adds the dependency column/index and request records. Stop services
and run explicit offline `python -m app.cli migrate` with the existing key.
Restore accepts initialized v1–v3 backups and migrates only the restored copy.
Dependency IDs intentionally survive deletion of an old prerequisite so recovery
can interrupt an orphaned queued task. Retention preserves prerequisites while
dependent tasks remain active. Account/target deletion still rejects active tasks.
