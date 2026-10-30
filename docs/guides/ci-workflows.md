# CI workflows

Use this inventory when choosing a CI entry point. The workflow file is the
owner of trigger and job facts; the [development guide](development.md) keeps
only the shared timeout and retention policy. Workflows that install browsers,
run tests, or build images require a GitHub-hosted runner for authoritative
validation.

| Workflow | Trigger | Purpose and overlap | Owner-of-fact links | Status |
| --- | --- | --- | --- | --- |
| [browser-cache-fix.yml](../../.github/workflows/browser-cache-fix.yml) | Push to `validation/browser-cache-fix-20261028`; manual | One-off routing/proxy regression for the browser-cache fix. The fast gate has a narrower synthetic browser preflight, not these focused routing tests. | [workflow](../../.github/workflows/browser-cache-fix.yml), [test boundary](development.md#test-boundaries) | **Keep for now** — its validation branch still exists; retire after the branch is closed or the regression is promoted to a maintained suite. |
| [browser-identity.yml](../../.github/workflows/browser-identity.yml) | Manual, browser or contracts mode | Diagnostic browser identity and lifecycle checks. It complements, rather than duplicates, the fast gate's browser preflight. | [workflow](../../.github/workflows/browser-identity.yml), [HTTP contract](../contracts/http-api.md) | **Keep** — useful operator-triggered diagnostics without account state. |
| [checks.yml](../../.github/workflows/checks.yml) | Pull requests, pushes to `main`, and manual; documentation-only changes excluded | Path-filtered non-publishing multi-architecture image builds. Frontend and backend checks are owned by the fast gate. | [workflow](../../.github/workflows/checks.yml), [fast gate](../../.github/workflows/fast-gate.yml) | **Keep** — required multi-architecture coverage without duplicate frontend/backend work. |
| [cpa-native-image.yml](../../.github/workflows/cpa-native-image.yml) | Manual; CPA source/tag path changes; `cpa-native-v*` tags | Builds and publishes the separately pinned CLIProxyAPI native OAuth image, with source/patch/digest metadata. Not part of the bridge fast gate. | [workflow](../../.github/workflows/cpa-native-image.yml), [CPA README](../../deploy/cpa/README.md) | **Keep** — independent release artifact. |
| [deployment.yml](../../.github/workflows/deployment.yml) | Manual dispatch (`publish`) | Reusable fast gate for amd64 app/worker verification and optional immutable GHCR publication. | [workflow](../../.github/workflows/deployment.yml), [deployment guide](deployment.md#immutable-ghcr-release-procedure) | **Keep** — the single manual release entry point. |
| Retired one-off workflows | No active trigger branches | `upstream-late-interrupt.yml` and `export-verified-app.yml` were historical diagnostics/export procedures and did not provide maintained bridge coverage. | Historical workflow paths are preserved in Git history. | **Retired** — their trigger branches no longer exist on the remote. |
| [fast-gate.yml](../../.github/workflows/fast-gate.yml) | PRs to main; pushes to main/validation/deployment branches; manual; reusable workflow call | Primary release gate: frontend, non-browser pytest, synthetic browser preflight, amd64 container startup/security checks, and optional digest-pinned GHCR publication. | [workflow](../../.github/workflows/fast-gate.yml), [deployment guide](deployment.md#immutable-ghcr-release-procedure) | **Keep** — canonical release gate and reusable implementation. |
| [full-regression.yml](../../.github/workflows/full-regression.yml) | Nightly schedule; manual; pushes to validation branches | Complete synthetic pytest regression plus frontend build. It is intentionally separate from fast-gate's bounded subset and never implies a release gate. | [workflow](../../.github/workflows/full-regression.yml), [development guide](development.md#test-boundaries) | **Keep** — scheduled broad coverage. |
| [novnc.yml](../../.github/workflows/novnc.yml) | Manual; push to `fix/novnc-cookie-context` | Account-viewer/noVNC frontend, API, and LAN browser acceptance. It overlaps only partially with fast-gate browser startup checks. | [workflow](../../.github/workflows/novnc.yml), [deployment guide](deployment.md#provision-and-start) | **Keep** — focused viewer regression until its branch fix is accepted; review branch trigger afterward. |
| [validation.yml](../../.github/workflows/validation.yml) | Manual; pushes to validation branches | Native OAuth bridge, patched upstream, and untouched upstream baseline validation. It overlaps with fast-gate only in general frontend setup; it is not a substitute for bridge pytest regression. | [workflow](../../.github/workflows/validation.yml), [CPA README](../../deploy/cpa/README.md) | **Keep** — required focused integration and upstream comparison. |
| [voice-image.yml](../../.github/workflows/voice-image.yml) | Manual dispatch only | Tests the pinned ChatGPT Web Voice fork and publishes its amd64 image plus immutable metadata. Independent of bridge image publication. | [workflow](../../.github/workflows/voice-image.yml), [Voice guide](../contracts/integrations/voice.md) | **Keep** — deliberate operator-controlled integration release. |

## Retention, caches, and logs

Artifacts contain only diagnostics, test reports, source/digest metadata, or the
explicitly requested verified image export; no image tarball is produced by the
fast gate. Release records and full-regression logs use 30-day retention, while
routine gate and diagnostic logs use 7 days. Short-lived verified exports use 2
days, and independent image metadata uses 14 days. These values are defined in
the workflows; the shared policy and timeout rationale are summarized in the
[development guide](development.md#ci-entry-points).

Dependency caches are keyed by the runner OS/architecture and lockfile hash.
Docker BuildKit caches use separate stable scopes for app and worker (or each
multi-architecture matrix target), preventing unrelated images from overwriting
one another. Restore/save pairs use the primary key returned by the restore step;
there are no broad fallback keys that could mix incompatible browser or lockfile
inputs.

The audit fixes in this inventory removed duplicate frontend/backend work from
`checks.yml`, a duplicate `checks.yml` upload of the same `check-logs/` directory,
and `amd64-images.yml`, an exact duplicate of `deployment.yml`. The one-off
`upstream-late-interrupt.yml` and `export-verified-app.yml` workflows were retired
after their trigger branches disappeared from the remote; `browser-cache-fix.yml`
remains because its validation branch still exists. [release.sh](../../deploy/release.sh)
still accepts gate runs recorded under the removed `amd64-images.yml` path so earlier
releases remain verifiable.
