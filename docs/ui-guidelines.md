# UI guidelines

The interface should make each operation understandable through its name, placement, and behavior. Users should be able to infer what a control does before reading supporting text. The default screen should stay focused on the current task instead of displaying tutorials or long explanations.

## Naming

- Use the same nouns as the domain model: **Accounts**, **Targets**, **Tasks**, and **Settings**.
- Name actions with a verb and an object: **Import accounts**, **Start login**, **Retry sync**, **Enter code**, **Take over browser**, **Continue**, and **Cancel task**.
- Use state names that describe what the system needs next: **Queued**, **Logging in**, **Waiting for code**, **Waiting for takeover**, **Sync pending**, **Completed**, **Failed**, and **Cancelled**.
- Do not expose implementation terms such as worker leases, storage state, PKCE, or cipher text in routine user flows.

## Layout

- Keep the primary navigation stable and limited to **Accounts**, **Targets**, **Tasks**, and **Settings**.
- Put the account identity, current status, and next available action together in each account row or detail view.
- Put destructive or irreversible actions at the end of the action group and require a clear confirmation.
- Keep task progress, code entry, takeover, continuation, cancellation, and retry in one task view.
- Show sensitive values as masked fields. Never put passwords, TOTP seeds, mailbox URLs, or access tokens in tables, URLs, ordinary responses, or logs.
- Use whitespace, grouping, and short labels before adding explanatory copy.

## Interaction

- Every control has one visible outcome and a predictable loading, success, and error state.
- Disable duplicate submissions while an operation is running and preserve the task state after refresh.
- Make the next required action prominent. For example, a task waiting for a code should show **Enter code** as the primary action.
- Keep **Cancel task** available while a task is queued, running, or waiting for takeover.
- Confirm before replacing credentials, deleting an account, or cancelling an active browser task.
- Report errors beside the affected control in plain language, with a retry action when retrying is safe.
- Use event updates for task progress; do not require users to reload a page to discover a state change.

## Guidance and empty states

- Do not place tutorials, setup essays, or implementation explanations on the default screens.
- Use a short empty-state sentence and one direct action, such as **No accounts yet. Import accounts**.
- Show help text only where a decision could otherwise be ambiguous, such as proxy selection or mailbox URL format.
- Prefer an example placeholder or inline validation to a separate tutorial page.

## Accessibility and consistency

- All actions must be keyboard reachable and have visible focus.
- Status must use text as well as color; color alone is not a state indicator.
- Preserve the same action order and status vocabulary across account and task views.
- Use responsive layouts that keep the primary action visible without horizontal scrolling.

