# Security boundaries

## Administrator and browser access

The administrator is trusted to configure accounts, destinations and routes and
to inspect or operate live account browsers. Provider websites, mailbox content,
remote services and browser traffic cross external trust boundaries. The bridge
does not make those external systems trusted by encrypting local storage.

Administrator requests are authenticated and same-origin; the session, CSRF,
cookie and password controls are defined by the [HTTP contract](../contracts/http-api.md).

The application is the authenticated gateway to the live desktop. Private
worker transport and same-host isolation are security boundaries; wire-level
authorization and filtering belong to the [account window contract](../contracts/account-window.md),
and process topology belongs to [runtime](runtime.md).

## Secrets at rest and during execution

Reusable account, browser and integration material is encrypted at rest, with
the key kept separate from SQLite. The decision and threat model are in
[ADR 002](decisions/002-encrypted-secrets.md); device restoration and temporary
runtime handling are defined by [runtime](runtime.md).

Public API responses expose presence flags, safe configuration and sanitized
events instead of stored secrets. Browser seeds, provider state and native-session
material are private. Validation errors omit submitted values. Browser traces,
HAR, video and screenshots are disabled. The live viewer streams pixels without
persisting captures, but an authorized operator can see sensitive account content
while the browser is open.

## Network and downstream boundaries

Explicit account routing and the absence of direct fallback are security
boundaries. The decision rationale is in [ADR 001](decisions/001-oauth-proxy.md);
downstream HTTP transport constraints belong to the [worker adapter contract](../contracts/worker-adapters.md).

Downstream management traffic is a separate authenticated service connection;
protocol-specific security requirements belong to [CPA](../contracts/integrations/cliproxyapi.md)
and [Voice](../contracts/integrations/voice.md).

A successful browser login does not by itself prove downstream installation, and
an uncertain write must not be treated as absent. Execution fencing and
reconciliation preserve that boundary; see [data and tasks](data-and-tasks.md)
and [ADR 003](decisions/003-execution-and-handoff.md). Tested behavior and
remaining limits are tracked in the [capability matrix](../roadmap.md).
