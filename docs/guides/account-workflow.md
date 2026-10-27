# Account workflow

The request and response shapes are defined in the [HTTP API contract](../contracts/http-api.md). This guide describes operator sequencing and recovery.

## Start login

From an account row, choose **登录 ChatGPT** to run the Voice login, or **登录 Codex** to run Voice followed by the dependent CLIProxyAPI authorization. Select only targets bound to the account and confirm the route before submitting. The UI disables a mode when its required target is missing; edit account bindings first. Repeated clicks with the same request identity are safe, while changing the selected mode requires a new request.

The Codex task remains blocked until Voice reaches `verified` after synchronization. A pending or failed synchronization requires an explicit retry or resolution. Failed, cancelled, interrupted, or missing prerequisites interrupt the blocked task. This ordering survives worker restart.

## Open an account window

Choose **账号窗口** to reopen the account's encrypted persistent browser device at ChatGPT. The console reuses a live same-account task or queues an idle browser window. A task blocked on an incomplete prerequisite is not eligible, while idle synchronization does not prevent opening a browser. The shared worker lock serializes browsers across accounts.

The window first shows a read-only monitor. Choose **接管** only after the worker reports `waiting_human`; the task page then offers **继续任务** or **取消任务**. Continue closes the browser and saves state; cancellation also preserves the device through the browser adapter. Closing the viewer does not extract credentials or synchronize a target. See the [account-window contract](../contracts/account-window.md).

## Recovery and compatibility

Schema v4 migration and backup/restore procedures are documented in the [deployment guide](deployment.md). Dependency IDs survive deletion of an old prerequisite so recovery can interrupt an orphaned queued task; retention preserves prerequisites while dependent tasks remain active. Account and target deletion still rejects active tasks.

Assisted real-account login and reuse are verified only when the main operator records serial acceptance. Unattended continuation, real-account browser reopening, and ordered authorization remain **unverified**; see [the roadmap](../roadmap.md).
