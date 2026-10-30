# Camoufox validation report (archived)

This is historical evidence. Its candidate status and migration TODOs have been
superseded by [ADR 004](../architecture/decisions/004-camoufox-primary-engine.md)
and [runtime](../architecture/runtime.md).

This report records the synthetic Camoufox evaluation completed on 2026-10-28.
It is archived because the evaluation is complete and the result is a migration
input, not a production capability guarantee.

## Scope

The evaluation used the open-source [Camoufox](https://github.com/daijro/camoufox)
repository at commit `39940c849a561534b315a225b2753cd4fa4bacf4` and its Python
package source version `0.5.7`. It used synthetic pages, profiles, cookies, and
storage only. No real account or provider credential was used.
The final hosted run is [40558866064](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40558866064).

## Results

The following behaviors passed in the hosted synthetic probe:

- Camoufox and its paired browser installed successfully.
- Playwright launched a Camoufox browser and persistent context.
- Account launch options applied locale and timezone.
- Main-page and Worker navigator values were coherent for user agent,
  platform, and hardware concurrency.
- WebGL values were readable.
- Local Storage survived a browser restart.
- Firefox correctly rejected Chromium CDP calls; Chromium-specific CDP APIs
  cannot be reused by the current window manager integration.

The following behaviors failed or remain unresolved:

- The existing device archive rejected Firefox's transient `lock` symlink.
  The probe could proceed only after temporarily adding `lock` to the archive
  exclusion set. The production archive implementation has not been changed.
- Cookie persistence was empty after direct restart and after the archive
  restore path. Cookie retention therefore remains unverified and is treated as
  a migration blocker.
- The Camoufox release emitted a warning that its UBO addon was absent. This
  did not prevent the synthetic page probe, but the production browser build
  must choose and verify an addon policy.
- Headed noVNC/Openbox control, proxy egress, OpenAI login compatibility, and
  real-account acceptance were not verified.

## Migration decision

Camoufox is a viable candidate browser engine for this project, but it is not a
drop-in replacement for the current Chromium integration. The next work belongs
in this repository:

1. Replace Chromium launch and CDP assumptions with a browser-engine adapter.
2. Persist and replay the complete Camoufox fingerprint/config per account;
   persistent Firefox storage alone does not guarantee a stable identity.
3. Extend profile archive validation for Firefox transient entries and resolve
   Cookie persistence before enabling migration.
4. Replace Chromium window-boundary control and update the worker preflight,
   Docker image, CI, and browser tests.
5. Re-run synthetic headed, proxy, isolation, and login probes before any real
   account acceptance. Real-account verification remains unverified.

No production code was changed by this evaluation.
