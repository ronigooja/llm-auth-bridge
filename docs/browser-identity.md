# Account browser identity, phase one

Each account has an encrypted browser identity preference alongside its existing
Chromium device archive. Supported platform preferences are `windows` (default)
and `macos`. They remain stable across login, idle account windows, retries and
Voice-to-Codex transitions. Different accounts can intentionally share the same
UA: a unique UA string per account would not represent ordinary Chromium usage.
The existing identity seed remains private; it is not injected into websites.

Before the managed page navigates, the worker uses Chromium's native CDP
`Emulation.setUserAgentOverride` to set a matching desktop User-Agent,
`navigator.platform`, UA Client Hints platform/version/architecture/bitness and
browser brand versions. Chrome's full version comes from `Browser.getVersion`
on the running executable, while the reduced UA uses its actual major version.
Windows uses a Windows 10 x64 identity; macOS uses an Intel macOS 15 identity.
The macOS reduced UA retains Chromium's compatibility token `10_15_7`, while
UA-CH reports `15.0.0`; these fields intentionally follow different version
formats.
No arbitrary UA string or random version is accepted. Browser updates naturally
change the browser version, while the account's OS preference stays unchanged.
Locale follows the saved account preference; proxy timezone resolution, fixed
account routing, sandboxing, private VNC and encrypted device storage are retained.

## Configuration API

These administrator endpoints require the existing authenticated session and,
for writes, same-origin CSRF validation:

- `GET /api/v1/accounts/{id}/browser-identity` returns `{"platform":"windows"}`
  or `{"platform":"macos"}`. Reading an unused account does not allocate a profile.
- `PUT /api/v1/accounts/{id}/browser-identity` accepts exactly one `platform`
  value from that set. It rejects queued, running, waiting or pending-sync tasks
  with HTTP 409. An unsupported platform or extra UA field returns HTTP 422.

Changing this preference preserves the account seed, credentials, proxy, saved
sessions and device archive. It changes the website-visible OS on the next task;
choose it before initial login and avoid changing it unnecessarily. Existing v1
and v2 encrypted profiles upgrade once to v3 with the Windows default, preserving
seed and account preferences. This is a profile-format upgrade, not a database
schema migration. The management UI does not yet expose a platform selector.

## Scope and limits

This phase emulates the identity of the bridge-managed page and its ordinary
same-process frames. It does not change the host OS, TLS implementation, fonts,
Canvas, Audio or GPU/WebGL renderer. Dedicated/shared workers, out-of-process
frames and manually opened additional tabs/popups are not covered by this
page-scoped override and remain unverified. APIRequestContext and downstream HTTP
clients are separate transports; their headers are not covered by this override.
This is not a complete anti-detect browser or AdsPower equivalent. Playwright's
normal automation behavior, including `navigator.webdriver`, is retained.

Synthetic headed CI checks cover the first navigation's UA and low-entropy
UA-CH headers, high-entropy negotiated headers, JavaScript properties, an iframe
and browser restarts for both platforms. No real account state is used.
`Browser identity diagnostics` additionally opens `https://browserleaks.com/ip`
with a fresh synthetic profile using public GitHub runner egress. It checks page
availability and basic identity properties without saving IPs, cookies, HTML,
screenshots or recordings. It does not verify a production account's proxy,
Cloudflare acceptance or complete absence of host-OS leaks.

Real-account behavior and reduction in Cloudflare challenges remain **unverified**.
