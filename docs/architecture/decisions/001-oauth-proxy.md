# ADR 001: OAuth through the account route

## Context

Browser authorization and server-side code exchange are separate transports.
A successful browser login can otherwise be followed by token exchange through a
different network identity. Implicit environment proxies or direct fallback also
make the effective account route ambiguous.

## Decision

When performing account authorization, require an explicit direct or proxy route
and use that route for both browser traffic and ordinary OAuth code exchange.
Direct mode ignores ambient proxies; proxy failure stops execution without a
direct fallback. GOST normalizes supported proxy types into a local endpoint
usable by the browser and HTTP client. The worker image pins its release and
architecture-specific checksums in the [Dockerfile](../../../Dockerfile).

When native CPA delegates exchange to the downstream extension, require explicit
route binding and attestation under the [CPA protocol](../../contracts/integrations/cliproxyapi.md).
Downstream management traffic remains a separate service connection.

## Consequences

An invalid or unavailable account route prevents authorization. Proxy secrets
must be passed through a private temporary GOST configuration. Browser and HTTP
clients can share routing without sharing identical headers or TLS behavior;
this decision does not promise transport fingerprint equivalence. Runtime route
implementation belongs to [routing.py](../../../app/routing.py); current runtime
behavior and trust boundaries are described in [runtime](../runtime.md) and
[security](../security.md).
