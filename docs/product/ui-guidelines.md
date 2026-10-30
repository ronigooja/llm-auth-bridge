# UI guidelines

When designing or updating management-console screens, apply these guidelines.

Use the domain nouns **Accounts**, **Targets**, **Tasks**, and **Settings**. Name actions with a verb and object: **Import accounts**, **Start login**, **Retry sync**, **Enter code**, **Take over browser**, **Continue**, and **Cancel task**. Status labels describe the next required action: **Queued**, **Logging in**, **Waiting for code**, **Waiting for takeover**, **Sync pending**, **Completed**, **Failed**, and **Cancelled**.

Keep navigation stable. Pair each account's identity, status, and next action. Keep progress, code entry, takeover, continuation, cancellation, and retry in one task view. Mask secrets and never place passwords, TOTP seeds, mailbox URLs, or tokens in URLs, tables, ordinary responses, or logs.

Disable duplicate submissions and preserve state after refresh. Keep **Cancel task** available while queued, running, or waiting for takeover. Confirm before replacing credentials, deleting an account, or cancelling active browser work. Report errors beside the affected control with a safe retry when appropriate. Show status as text as well as color; keep all actions keyboard reachable with visible focus.

Use short empty states and one direct action. Explain a decision inline where needed, such as proxy URL format. Do not put setup essays or implementation terms such as leases, PKCE, storage state, or cipher text in routine user flows.

## Account routing

Accounts with an unset route default to proxy routing and may preselect available CLIProxyAPI targets. Existing explicit routes and bindings, including empty bindings, are preserved until save. Proxy URLs use one visible text field (`http://`, `https://`, or `socks5://`); percent-encode reserved credentials. Stored proxy credentials are omitted from lists and loaded only in the authenticated editor.

## Browser takeover window

Design the takeover entry point as a dedicated resizable window, reserve it before requesting takeover, show preparation text, and retain an **Open takeover window** link when popups are blocked. Use the authenticated same-origin viewer without credentials in the URL. Follow the [account-window contract](../contracts/account-window.md) for transport, resize, monitor, takeover, and lifecycle behavior.
