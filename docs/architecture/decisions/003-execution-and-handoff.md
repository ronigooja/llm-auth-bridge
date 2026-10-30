# ADR 003: Serial execution and credential handoff

## Context

Human authorization can hold a browser open for minutes. Worker crashes,
expiration and cancellation can overlap with downstream writes whose outcome is
unknown. Replaying an OAuth callback or overwriting a refreshed remote credential
can damage an otherwise successful authorization. Multiple browser owners must
also be prevented from sharing the private desktop.

## Decision

Use one host-wide process lock with SQLite transaction fencing, execution IDs and
leases so browser work remains serial and owned. Do not replay expired browser
authorization or uncertain native callbacks; reconcile durable state instead.
Persist pending results before leaving the browser and require readback of the
documented credential, identity and route contract before success.

Record a downstream write attempt before it can begin. Later retries reconcile
first, and only an adapter's explicit proof that no write was possible clears
uncertainty. Local discard preserves remote identity and audit without deleting
the remote account. Downstream owns CPA refresh rotation, while Voice maintenance
uses the same queue and saved sessions.

Native integration availability depends on its server contract; deployment
acceptance is tracked in the [roadmap](../../roadmap.md).

## Consequences

Serial throughput and reconciliation are deliberate consequences of avoiding
duplicate authorization and ambiguous remote writes. Pending credentials remain
encrypted beyond the browser lifetime.

The current lifecycle is documented in [data and tasks](../data-and-tasks.md).
[queue.py](../../../app/queue.py), [worker.py](../../../app/worker.py) and the
[worker adapter contract](../../contracts/worker-adapters.md) define the execution
and synchronization boundaries. Downstream requirements belong to
[CPA](../../contracts/integrations/cliproxyapi.md) and [Voice](../../contracts/integrations/voice.md).
