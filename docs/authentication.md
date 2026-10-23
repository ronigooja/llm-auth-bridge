# Authentication flow

Imports use `account----password----totp_secret[----mailbox_url]`. The fourth field is an HTTPS mailbox entry point and is never interpreted as a proxy. Import preview reports malformed and duplicate rows before confirmation. Secrets are encrypted with AES-GCM.

Login tasks must have an explicit direct or proxy route. TOTP is attempted only within a bounded time window. Mailbox reading uses an isolated context, records a baseline, and accepts only a message whose sender, recipient, purpose, and timestamp match the request. Ambiguous or changed pages transition to `waiting_human`; the user can enter a code or take over the already-running browser.

