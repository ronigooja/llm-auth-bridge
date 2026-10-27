# Security boundaries

## Administrator and browser access

The administrator is trusted to configure accounts, destinations and routes and
to inspect or operate live account browsers. Provider websites, mailbox content,
remote services and browser traffic cross external trust boundaries. The bridge
does not make those external systems trusted by encrypting local storage.

[main.py](../../app/main.py) enforces administrator sessions and same-origin
request checks. Passwords use Argon2id. Session tokens are random; SQLite stores
only their SHA-256 hashes. Cookies are HttpOnly, SameSite Strict and Secure by
default, with a twelve-hour default lifetime. Authenticated writes require a
per-session CSRF header and origin validation. Login attempts are rate limited;
password changes revoke every session and a hash recheck fences concurrent login
with the old password. Endpoint details belong to the
[HTTP contract](../contracts/http-api.md).

Live desktop access requires a valid session, explicit same-origin WebSocket
Origin, eligible task and active execution lease. Connections remain pinned to
the initial task/account/execution and are revalidated while idle. Logout,
cancellation, lease expiry, task termination or browser closure revokes access.
Interactive takeover requires human-wait state. Monitor input restrictions are
enforced by a fail-closed server RFB filter, not just noVNC's `viewOnly` option;
bounded desktop resizing is the permitted geometry exception. See the
[account window contract](../contracts/account-window.md) for the wire rules.

TigerVNC uses unauthenticated RFB only inside the worker. VNC/websockify ports are
not published; the app is the authenticated external gateway. Publishing those
ports bypasses that gateway. Same-host deployment, container isolation and the
private service network are therefore part of the security boundary.

## Secrets at rest and during execution

Account passwords, TOTP seeds, mailbox URLs, proxy routes, downstream
configuration, browser preferences/state/devices, native-session references,
commands and pending credentials are encrypted with AES-GCM. The key is mounted
separately from SQLite. Device archives additionally authenticate the account ID.
The key check detects a mismatched key during startup. Losing the key prevents
recovery of encrypted records; database-only backups are insufficient. See
[ADR 002](decisions/002-encrypted-secrets.md), [crypto.py](../../app/crypto.py)
and the [deployment guide](../guides/deployment.md).

Encryption protects stored material; app and worker necessarily decrypt the
material needed for their current operation. The worker restores account devices
into restricted temporary directories on production tmpfs and removes them after
use. Archive validation rejects path traversal, links and oversized payloads.
GOST receives proxy secrets through a private temporary configuration rather
than command-line arguments. Browser sandboxing, an unprivileged user,
`no-new-privileges` and the Playwright seccomp configuration constrain execution;
they do not replace isolation from a compromised host.

Public API responses expose presence flags, safe configuration and sanitized
events instead of stored secrets. Browser seeds, provider state and native-session
material are private. Validation errors omit submitted values. Browser traces,
HAR, video and screenshots are disabled. The live viewer streams pixels without
persisting captures, but an authorized operator can see sensitive account content
while the browser is open.

## Network and downstream boundaries

Accounts require an explicit direct or proxy route. Browser traffic and ordinary
OAuth exchange use the same selected account route; a failed proxy never falls
back to direct access. Direct transports ignore ambient proxy variables. GOST
normalizes supported proxy protocols to one local endpoint. Proxy timezone lookup
also uses the account route and fails closed before navigation. These controls
are implemented by [routing.py](../../app/routing.py),
[route_timezone.py](../../app/route_timezone.py) and
[browser.py](../../app/browser.py); their rationale is in
[ADR 001](decisions/001-oauth-proxy.md).

Downstream management traffic is a separate authenticated service connection.
For native CPA OAuth, the extension owns token exchange and must attest the
explicit account route along with identity and credential readback; the bridge
cannot infer that guarantee from a generic successful HTTP response. Voice
compatibility likewise requires the documented server contract. Protocol
requirements belong to [CPA](../contracts/integrations/cliproxyapi.md) and
[Voice](../contracts/integrations/voice.md).

A successful browser login alone does not prove downstream installation, and a
possible write cannot safely be treated as absent after a timeout. Execution
fencing and reconciliation preserve this uncertainty rather than overwriting a
remote credential; see [data and tasks](data-and-tasks.md) and
[ADR 003](decisions/003-execution-and-handoff.md). Synthetic tests do not establish
real provider acceptance or complete browser identity isolation. The
[capability matrix](../roadmap.md) records those limits.
