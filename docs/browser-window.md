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
clipboard, desktop resize, exclusive ClientInit, unknown client messages and
unsupported extensions close the connection. The client should also set
`viewOnly`, `shared`, and disable resize requests; client settings alone are not
an authorization boundary.

VNC remains internal; do not expose its ports. The viewer streams live frames
without storing screenshots, recordings, browser state or credentials. Real-account
monitoring remains unverified until serial real-account acceptance is completed.
