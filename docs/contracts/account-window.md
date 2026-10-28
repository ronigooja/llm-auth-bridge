# Account window transport

The account window uses the task's live browser. Opening its monitor does not
pause automation or create a second browser. Interactive takeover still requires
the worker to enter `waiting_human` before connecting.

- `WS /api/v1/tasks/{id}/monitor` allows `running` and `waiting_human` tasks.
- `WS /api/v1/tasks/{id}/takeover` allows only `waiting_human` tasks and forwards
  the interactive VNC stream.

Both endpoints require an authenticated session, an explicit same-origin Origin,
a non-cancelled task with `takeover_available`, and a live execution lease. Each
connection is pinned to its initial task, account and execution owner. Validation
runs before forwarding traffic and every 500 ms while idle. Logout, lease expiry,
execution replacement, cancellation, unavailable browser or task completion closes
the connection. These rules apply to login and browser-window tasks alike.

The monitor enforces read-only operation on the server. Its binary RFB stream
filter supports RFB 3.8, None security on the internal transport, and shared
ClientInit. It forwards bounded pixel-format configuration, sanitized passive
image/update encodings, framebuffer requests and bounded Fence replies. It
buffers fragmented RFB messages across WebSocket chunks. Keyboard, pointer,
clipboard-send, exclusive ClientInit, unknown client messages and unsupported
extensions close the connection. Server clipboard notifications remain available
to the monitor, so remote text can be copied into the account window. Interactive
takeover forwards clipboard-send messages through the authenticated transport;
the viewer also exposes a textarea fallback for browsers that deny the Clipboard
API. A geometry-only exception accepts one desktop
at origin (0, 0), with dimensions 64–4096 pixels per axis, at most 8,847,360 pixels,
and zero screen flags. Fragmented resize messages are validated before forwarding.
ExtendedDesktopSize negotiation is allowed. The client remains `viewOnly` and
`shared`; client settings alone are not an authorization boundary.

The authenticated `/account-viewer` and `/account-viewer.js` use Debian noVNC's
core renderer with a small toolbar. They request a remote desktop matching
the iframe's CSS dimensions and display its framebuffer at 1:1 CSS scale. The
small noVNC 1.3 adapter permits geometry requests in view-only mode; input is
still disabled in monitor mode and rejected by the monitor's server filter. The
worker runs TigerVNC with desktop resizing enabled and Openbox, so a maximized
Chromium window follows screen size changes. Browser chrome remains visible.
This replaces Xvfb/x11vnc's fixed desktop and the previous local scaling mode.
Changing popup aspect ratio must resize the desktop instead of adding bars or
cropping. VNC and its X display remain private to the worker.

The toolbar's Fullscreen button enters browser fullscreen; pressing Escape exits
it. During takeover, Clipboard opens a text area that sends text to the remote
browser and copies received text to the local clipboard, with a selection-based
fallback when the Clipboard API is unavailable. Clipboard controls remain hidden
for read-only monitoring. These controls apply to both login and browser-window
account tasks.

VNC remains internal; do not expose its ports. The viewer streams live frames
without storing screenshots, recordings, browser state or credentials. Real-account
monitoring remains unverified until serial real-account acceptance is completed.
