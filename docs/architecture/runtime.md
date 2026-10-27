# Runtime and account browser identity

## Process topology

The [worker image](../../Dockerfile) runs `bridge-worker` under `tini` as the
unprivileged bridge user. Its entrypoint starts TigerVNC's `Xtigervnc` X display,
waits for the display socket, starts Openbox, waits for window-manager readiness,
then starts websockify and the Python worker. Shutdown waits for the worker to
close its browser before stopping the desktop processes. The app and worker use
the shared data volume and lock defined in [Compose](../../docker-compose.yml).

TigerVNC binds its RFB listener to localhost with internal None security;
websockify is reachable only inside the private service network. Administrator
access passes through the application's authorized WebSockets. Monitor and
interactive takeover reuse the task's current browser; opening a monitor does
not pause automation. See the [account window contract](../contracts/account-window.md)
for authorization and RFB filtering.

The production desktop starts at 1920×1080 with remote resizing enabled. The
viewer requests a desktop matching its iframe's CSS dimensions and renders at
1:1 CSS scale. Openbox keeps the Chromium window maximized as the desktop changes.
`fit_browser_window` first clears stale restored window bounds, then fits and
maximizes the native window. Browser chrome remains visible. A fixed framebuffer
smaller than the browser loses pixels, which client scaling cannot recover; the
runtime therefore coordinates desktop and window geometry instead of relying on
local scaling. Production uses TigerVNC/Openbox rather than Xvfb/x11vnc.

The managed browser uses `no_viewport=True`, so content follows the actual window.
Saved profile viewport/screen values are defaults for other context consumers,
not a fixed production framebuffer or a promise of unique account dimensions.
Runtime source: [browser.py](../../app/browser.py),
[browser_identity.py](../../app/browser_identity.py),
[account-viewer.js](../../app/static/account-viewer.js).

## Persistent devices and preferences

An account has three related forms of state:

- An encrypted profile stores stable preferences, including platform and locale,
  and a private identity seed. The seed is not injected into websites.
- An encrypted device archive stores a restricted native Chromium user-data
  directory. Each task restores it into a private temporary directory and launches
  a persistent Chromium context. The same account device is reused for browser
  windows, Voice and Codex tasks; other accounts use separate directories.
- Encrypted browser session state supports legacy import and session checkpoints.
  The device archive also explicitly checkpoints session cookies across restarts.

Chromium closes before device snapshotting, including ordinary failure and
cancellation paths. A valid execution lease is required to publish a device
checkpoint, even after cancellation. Failed initialization or unconfirmed browser
shutdown preserves the previous archive. A hard crash before checkpointing can
lose current-task changes. Archives exclude caches, crash material and process
locks; native sessionStorage remains tab scoped. This is persistent account
storage, not a byte-for-byte archive of every Chromium artifact.

Restoration validates paths, file types and size budgets before extracting.
Authenticated encryption binds each archive to its account ID, preventing
cross-account ciphertext substitution. See [browser_device.py](../../app/browser_device.py)
and device controls in [worker.py](../../app/worker.py). Profile allocation and
upgrades are committed under task ownership before navigation. Device archive
format, profile format and database schema have independent version lifecycles.

Proxy tasks resolve the route's exit timezone before navigation and persist the
verified IANA timezone in the profile. Lookup failure stops the task rather than
switching routes or silently selecting UTC. Locale remains an account preference;
it does not automatically follow IP geolocation. See
[route_timezone.py](../../app/route_timezone.py).

## Platform identity and limits

Profile format v3 stores `windows` (default) or `macos`. Older profile formats
upgrade while preserving the account seed and preferences. Platform changes keep
the existing device archive and sessions and apply on the next task; API mutation
constraints belong to the [HTTP contract](../contracts/http-api.md).

Before the managed page navigates, CDP `Emulation.setUserAgentOverride` supplies
matching desktop UA and UA Client Hints using the running Chromium's version from
`Browser.getVersion`. Windows advertises Windows 10 x64; macOS advertises Intel
macOS 15. The macOS reduced UA retains Chromium's compatibility token `10_15_7`
while UA-CH uses `15.0.0`. A page initialization script aligns legacy
`navigator.platform` for documents and ordinary frames. Arbitrary user agents and
invented browser versions are not accepted. Different accounts may share the same
UA, as ordinary Chromium users do. The managed browser disables Blink's
`AutomationControlled` feature, but this does not establish general stealth.

These controls do not change the Linux host, fonts, Canvas, Audio, GPU/WebGL,
TLS implementation or physical hardware. Dedicated Worker globals are not
rewritten. Out-of-process frames, extra tabs/popups and platform-specific runtime
signals remain outside the verified page identity scope. Playwright request
contexts and downstream HTTP clients are separate transports. Persistent storage
and a coherent configured platform do not establish complete fingerprint
isolation, anti-detect equivalence or provider challenge avoidance. Current
acceptance evidence and gaps belong to the [capability matrix](../roadmap.md).
