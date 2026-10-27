# ADR 003: Serial execution and credential handoff

## Context

Human authorization can hold a browser open for minutes. Worker crashes,
expiration and cancellation can overlap with downstream writes whose outcome is
unknown. Replaying an OAuth callback or overwriting a refreshed remote credential
can damage an otherwise successful authorization. Multiple browser owners must
also be prevented from sharing the private desktop.

## Decision

When claiming work, combine a SQLite immediate transaction with a shared process
file lock. Fence owned mutations using a random execution ID and live lease;
renew heartbeats independently of browser activity. Keep execution on one host
with one shared lock and serialize browser tasks, including human waits.

When an ordinary browser execution expires, interrupt it rather than replaying
code exchange. When native downstream state exists, reconcile that state and
poll an uncertain exchange rather than resubmitting callbacks. After browser
credential capture, persist an encrypted pending result and finish browser
teardown before claiming another task. Retry synchronization using stored
material without reopening the login browser.

When a downstream write can begin, durably record the attempt in the same
transaction that checks cancellation. Later retries reconcile before writing.
Only an adapter's explicit proof that no write was possible clears that
uncertainty. An unresolved conflict requires administrator-confirmed local
discard, preserving remote identity and audit without deleting the remote account.
Require readback that proves the documented credential, identity and route
contract before declaring success; generic server reachability is insufficient.

When handoff succeeds, downstream owns CPA refresh rotation and the bridge
removes its active pending credential copy. Voice maintenance uses the same queue
and saved web sessions. A native integration is available only when its server
implements the required contract; real deployment acceptance is recorded in the
[capability matrix](../../roadmap.md).

## Consequences

Throughput is deliberately serial, and human waits block other browser work.
An expired browser task may need a fresh authorization. Possible remote writes
can prevent ordinary cancellation and require operator reconciliation. Native
recovery can retain account/target binding until its remote outcome is settled.
Pending credentials need durable encryption and retention beyond browser lifetime.

The current lifecycle is documented in [data and tasks](../data-and-tasks.md).
[queue.py](../../../app/queue.py), [worker.py](../../../app/worker.py) and the
[worker adapter contract](../../contracts/worker-adapters.md) define the execution
and synchronization boundaries. Downstream requirements belong to
[CPA](../../integrations/cliproxyapi.md) and [Voice](../../integrations/voice.md).
