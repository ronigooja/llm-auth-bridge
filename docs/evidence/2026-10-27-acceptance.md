# Acceptance evidence log

This log preserves dated evidence supporting the status in the [roadmap](../roadmap.md).
These are historical facts; they do not establish verification beyond the stated scope.

## Evidence supporting status judgments

- **Assisted account observations, 2026-10-25:** source
  [`0b1c48e`](https://github.com/ronigooja/llm-auth-bridge/tree/0b1c48e26c2722514d3b8786234b459cf2ac7a1f)
  reused one persistent device and configured proxy. After operator human verification,
  stored TOTP completed ChatGPT login and Voice storage readback succeeded. Later
  Codex tasks reused the provider session without new email/password/TOTP; operator
  account selection and consent completed OAuth and downstream synchronization.
  The [original observation in Git history](https://github.com/ronigooja/llm-auth-bridge/blob/d22cdb8034f736aa4deca6a08de87dbc64f30435/docs/verification-persistent-devices-20261025.md#subsequent-serial-real-account-verification)
  preserves provenance. These observations establish assisted authorization and
  session reuse, not unattended flow or inference/audio usability. Later chooser
  and consent automation has synthetic coverage, not renewed real-account acceptance.
- **Adaptive desktop, 2026-10-26:** source
  [`e55ae99`](https://github.com/ronigooja/llm-auth-bridge/tree/e55ae999dfc821eb41aee3818285dace0830779e),
  [deployment run 40304619566](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40304619566),
  passed partitioned backend/frontend checks, selected browser acceptance, native
  ARM64 builds and nonroot worker-image resizing. This was not a full pytest run.
  [Retina viewer run 40305857158](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40305857158)
  at `b51eb0469917f2483e0ea10bd9af19cf4d02f391` added synthetic WebKit DPR 2 checks;
  production files were unchanged. Neither run establishes physical Safari or
  real-account visual acceptance.
- **Native extension, 2026-10-25:** bridge
  [`bf744aa`](https://github.com/ronigooja/llm-auth-bridge/tree/bf744aa5a3c7f867d9e57ab392af9933cbf3c280),
  [validation run 40218832546](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40218832546),
  passed the full synthetic bridge suite, frontend checks, focused native API
  tests and native server compilation. The overall run failed: both untouched and
  patched upstream Go suites failed heartbeat/store-corruption tests, and only the
  patched full run timed out in `TestResponsesLateInterruptDoesNotPoisonNextCreate`.
  The failure sets did not match. [Diagnostic run 40219551648](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40219551648)
  at `a843bb362e2efcf192957f6699a6960a28fcd47b` passed isolated repetitions on both
  inputs but did not establish the cause or turn the full run into a pass.
  Exact native inputs are pinned in [source metadata](../../deploy/cpa/source.json).
- **Voice overlay:** [pinned source](../../deploy/voice/source.json), fork `32d696a`,
  passed synthetic Go and disposable HTTP acceptance before ARM64 deployment.
  [The original deployment record in Git history](https://github.com/ronigooja/llm-auth-bridge/blob/d22cdb8034f736aa4deca6a08de87dbc64f30435/docs/roadmap.md#voice-overlay-deployment-record-2026-10-24)
  records management acceptance; the later assisted observation above establishes
  storage synchronization only. The [Voice contract](../contracts/integrations/voice.md)
  describes the disposable harness and its limits.

## Historical regression gate

The baseline `d22cdb8` [Checks run 40408984960](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40408984960)
failed the frontend case `keeps account editor busy until new route and bindings
finish refreshing` because the expected account-editor dialog was absent. The
same case failed on the documentation-only revision `c9d7441` in
[run 40473738235](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40473738235).
The production frontend build and targeted Codex continuation preflight could run
following that failure; their completion did not make the overall check pass.
The baseline regression remained unresolved in this evidence record.
