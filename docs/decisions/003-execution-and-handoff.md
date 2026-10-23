# Serial execution and credential handoff

Use both a SQLite immediate claim and a shared file lock. The database fences every owner write by execution ID/lease, while the lock prevents two browser processes even across human waits. Browser crashes interrupt authorization and never replay OAuth code exchange. Credentials move through an encrypted pending result after browser teardown; sync retries do not retain browser resources.

Durably mark a possible downstream write in the same transaction that checks cancellation. A later retry reconciles rather than overwriting potentially rotated remote tokens. Preflight failures can safely clear that uncertainty only when the adapter explicitly proves no write was possible. An unresolved conflict needs explicit administrator confirmation to discard local material, while preserving remote ID/audit and avoiding remote deletion. CPA owns refresh rotation after successful handoff; the bridge deletes its active pending copy. Voice maintenance uses the same queue and only saved web sessions.

Choose GOST 3.3.1 release binaries with architecture-specific SHA-256 checksums to normalize account proxy protocols. Both browser and code exchange use the local routed endpoint. GOST secrets are passed in a private temporary config; direct mode ignores ambient proxies. Service management traffic remains a separate connection.

Do not invent native downstream verification when the deployed API cannot attest identity, credential and explicit route. The reviewed voice APIs do not meet that contract. Keep the compatibility client and server requirement explicit, and require actual deployment acceptance before advertising native voice support.
