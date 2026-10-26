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


## Account routing form

New accounts and existing accounts whose route is still `unset` default to proxy routing. These unconfigured accounts preselect available CLIProxyAPI targets if no targets are bound. Existing explicit direct/proxy routes and their saved bindings are preserved, including empty bindings. Defaults are persisted only when the user saves the form. Proxy configuration uses one visible text URL input, such as `http://user:password@host:8080` or `socks5://host:1080`. Percent-encode reserved characters in credentials. The UI validates and converts this URL into the existing `{server, username?, password?}` API contract; `socks5h` normalizes to the worker's SOCKS5 route with remote DNS. Editing an existing proxy with an empty URL retains its encrypted configuration; selecting proxy for an account without one requires a URL. The normal account list omits stored proxy credentials; opening an account editor requests the saved configuration through an authenticated administrator action so it can be reviewed and changed.

Form inputs and selects share one base style: 43 px minimum height, inherited 13 px label font, 1 px border, 6 px radius, and 11 px vertical padding. Selects add only right-side space and a chevron. Inputs, selects, and textareas share a keyboard-focus outline; network routing has no separate size override.

The account form displays entered account passwords, authenticator keys, and proxy URLs as visible text at the administrator's request. Existing encrypted secret values are loaded into the administrator account editor for review; leaving an edit field unchanged retains the saved value.

## Browser takeover window

- The **Take over browser** action opens a dedicated, resizable window from the user click. Desktop windows use up to 1600 × 1000 available screen pixels; smaller screens use the available screen, and mobile browsers may open a full-page tab. The viewer no longer occupies a small embedded task panel.
- Reserve the window before awaiting the authenticated takeover request, and navigate only after the worker reports a paused, available browser session. Show preparation text while waiting.
- Keep a manual **Open takeover window** link when popups are blocked or closed. Reuse and focus the existing window on repeated clicks. Closing the viewer does not continue or cancel the task; users return to the task view and choose **Continue task**.
- Use the existing same-origin, cookie-authenticated noVNC tunnel without credentials in the URL. Remove the viewer opener. Close managed windows when automation resumes, takeover is revoked, the task terminates, or its detail view unmounts; a browser-opened fallback tab remains under user control. Server authentication and takeover revocation still apply.
- Popup behavior is covered by synthetic browser-window mocks; real-account takeover remains unverified.
