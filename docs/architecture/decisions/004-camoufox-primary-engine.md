# ADR 004: Camoufox as the primary browser engine

## Context

The production worker previously depended on Chromium-specific launch flags,
CDP window control, and Chromium profile archives. The Camoufox evaluation
showed that Firefox profile storage and cookies require an explicit archive
format and that Chromium CDP calls cannot be reused.

## Decision

Camoufox is the single production browser engine. The worker uses the pinned
Camoufox Python package and its paired Firefox build through a small adapter.
Each account stores an encrypted, replayable Camoufox fingerprint/config and
reuses it on every launch. Existing Chromium profiles are not converted: an
account gets a new Firefox profile and must authenticate again. Device archives
carry an explicit Camoufox format marker; unmarked Chromium archives remain
stored but are never restored.

## Consequences

Cookie and Local Storage persistence are validated across close, archive,
restore, and restart before real account migration. Window control uses the
Firefox desktop/window APIs available to the adapter rather than CDP. Browser
upgrades require re-running the synthetic identity, persistence, proxy, and
headed/noVNC checks.
