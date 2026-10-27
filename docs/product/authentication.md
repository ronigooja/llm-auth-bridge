# Authentication behavior

Import lines use `account----password----totp_secret[----mailbox_url]`; the fourth field is a mailbox URL, never a proxy. Preview validates rows and case-insensitive identity conflicts. Confirmation rejects any invalid row and commits atomically. Imported accounts start without a route or target binding; choose direct or proxy routing and bind a target before starting a task.

The worker runs headed Camoufox/Firefox in a private TigerVNC/Openbox desktop. The adapter classifies visible provider forms, waits for delayed transitions, and pauses for takeover on unknown, CAPTCHA, third-party, device, or ambiguous code steps. TOTP uses at most two distinct validity windows. Password submission is not blindly repeated. Imported identity, final token identity, callback parameters, and expiry must match before a result is accepted.

Auth-files and native OAuth targets use the account's explicit route. Native OAuth requires the patched CLIProxyAPI extension; the bridge submits the callback once and stores only an encrypted native-session reference. It does not silently fall back or replay uncertain exchanges. ChatGPT Web sessions are reused only while authenticated; expired sessions require an administrator-triggered login.

Account devices preserve provider sessions between tasks. Their persistence,
platform preferences and identity limits are defined in [runtime architecture](../architecture/runtime.md).
Acceptance of assisted login, reuse and unattended flow is recorded in
[the roadmap](../roadmap.md).

No generic webmail reader is enabled. Mailbox URLs are validated and encrypted; code entry or same-session takeover is required. Ambiguous or stale messages are not selected automatically.

## Human operation

Task controls support code entry, takeover, continue, cancel, and safe synchronization retry. Takeover binds the authenticated WebSocket to the live waiting task and lease. Waiting expires after thirty minutes. Cancellation closes the browser; lease checks prevent a stale worker from overwriting account state. Account-window behavior is defined in the [contract](../contracts/account-window.md).

Codex continuation on `/choose-an-account` requires one visible exact identity match (case insensitive). Multiple, conflicting, or unsupported controls pause for review. Consent waits for one visible enabled **Continue** button; uncertain clicks are not replayed. Assisted, operator-reviewed login and reuse are distinct from unattended continuation, which remains **unverified**.
