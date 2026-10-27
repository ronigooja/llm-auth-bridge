# Capabilities and remaining acceptance

This is the authority for capability status and outstanding verification. Status
was consolidated on 2026-10-27 against source baseline
[`d22cdb8`](https://github.com/ronigooja/llm-auth-bridge/tree/d22cdb8034f736aa4deca6a08de87dbc64f30435).
Implementation, synthetic acceptance, assisted real-account observations and
unattended operation are distinct. A management connection or stored credential
readback does not prove provider usability, runtime reload, or actual egress.

## Capability matrix

| Capability | Established evidence | Remaining acceptance |
| --- | --- | --- |
| Administrator sessions, CSRF, encrypted CRUD/import, explicit migration, backup/restore | Implemented; synthetic suites cover these paths | Production restore with the matching key remains an operator acceptance task |
| Serial queue, leases/fencing, recovery, manual inputs, SSE, pending-sync retry | Implemented; synthetic suites cover cancellation and uncertain writes | Provider-specific timeout/recovery behavior remains unverified |
| OpenAI password, TOTP, browser session and legacy OAuth adapter | Synthetic fixtures; assisted ChatGPT login and assisted Codex authorization observed on 2026-10-25 | Fully unattended login, all real challenge branches, Codex inference remain unverified |
| Per-account encrypted Camoufox/Firefox device and Voice-to-Codex session reuse | Hosted persistence/isolation tests and ARM64 sandbox acceptance; assisted reuse observed | Unattended chooser/consent continuation in the current source remains unverified with real accounts |
| Account OS preference and Camoufox fingerprint configuration | Native page-scoped platform override and synthetic headed checks for Windows/macOS | Worker globals, out-of-process frames, additional pages and host/hardware signals remain unverified; reduced Cloudflare challenges unverified |
| Account windows, monitor/takeover, adaptive desktop | Hosted synthetic RFB/noVNC checks; ARM64 TigerVNC/Openbox resizing and packaged Camoufox/Firefox popup checks | Physical Safari/Retina visual confirmation and current real-provider window behavior remain unverified |
| HTTP/HTTPS/SOCKS5 routing with no direct fallback | Synthetic proxy isolation and production sandbox checks | Provider-observed egress and downstream runtime routing remain unverified |
| CLIProxyAPI auth-files synchronization | Mock contracts, deployed management access, assisted Codex synchronization observed | Codex inference, refresh rotation and full runtime egress acceptance remain unverified |
| CLIProxyAPI native OAuth (`cpa-native-oauth-v1`) | Client implemented; focused patched native API tests and server compilation passed | Requires patched target; deployed native authorization, commit/recovery, runtime reload and real-account usability remain unverified |
| Voice `bridge-v1` client and patched gateway | Mock/disposable HTTP contract checks, ARM64 overlay deployment, assisted ChatGPT credential synchronization observed | Voice audio, actual egress, token expiry/renewal and unattended maintenance remain unverified |
| Native unpatched Voice administrator CRUD synchronization | Unsupported: reviewed native APIs cannot attest exact credentials and explicit route | Requires a compatible server layer; native CRUD alone is insufficient |
| Automatic webmail | Freshness/security primitives only; manual code/takeover available | No site-specific reader; automatic retrieval remains unsupported until a site contract and adapter are accepted |
| Linux containers | ARM64 app/worker build and nonroot sandbox/runtime checks passed | amd64 runtime acceptance remains unverified; Docker build definitions do not establish runtime acceptance |

## Evidence supporting current judgments

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
  Exact native inputs are pinned in [source metadata](../deploy/cpa/source.json).
- **Voice overlay:** [pinned source](../deploy/voice/source.json), fork `32d696a`,
  passed synthetic Go and disposable HTTP acceptance before ARM64 deployment.
  [The original deployment record in Git history](https://github.com/ronigooja/llm-auth-bridge/blob/d22cdb8034f736aa4deca6a08de87dbc64f30435/docs/roadmap.md#voice-overlay-deployment-record-2026-10-24)
  records management acceptance; the later assisted observation above establishes
  storage synchronization only. The [Voice contract](contracts/integrations/voice.md)
  describes the disposable harness and its limits.

## Current regression gate

The baseline `d22cdb8` [Checks run 40408984960](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40408984960)
failed the frontend case `keeps account editor busy until new route and bindings
finish refreshing` because the expected account-editor dialog was absent. The
same case failed on the documentation-only revision `c9d7441` in
[run 40473738235](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40473738235).
The production frontend build and targeted Codex continuation preflight can run
following that failure; their completion does not make the overall check pass.
Resolve this baseline regression before claiming the complete current integration
check is green. This documentation change does not alter application or test code.

## Required before full product acceptance

1. Synthetically accept a deployed native CPA target's staging/commit recovery,
   immutable binding, route use and credential ownership. Resolve or diagnose the
   recorded full upstream Go failures without suppressing their verdicts.
2. Verify current unattended ChatGPT-to-Codex continuation serially with a securely
   supplied test account. Exercise password, TOTP/email/manual challenge branches,
   proxy failure behavior, session reuse and account-window recovery. Do not infer
   current automation acceptance from earlier assisted observations.
3. Confirm CPA runtime reload, actual egress, refresh ownership and Codex inference;
   confirm Voice audio, actual egress, expiry/renewal, saved-session maintenance
   and restart behavior with the compatible deployed service.
4. Accept amd64 container runtime, the production Camoufox sandbox on each target
   host, physical client visual behavior, and production backup/restore using the
   matching key. Preserve database/image rollback compatibility during upgrades.
5. Obtain the actual mailbox site's contract before adding an isolated reader with
   pinned public egress, redirect controls, pre-request baseline, bounded polling,
   freshness and ambiguity checks.

Real credential acceptance is serial and main-agent owned under [AGENTS.md](../AGENTS.md).
No real-account login or deployment is part of this documentation refactor.

## Later scope

Other vendors, IMAP, concurrent browser scheduling, multi-user authorization,
multi-host queues and automated CAPTCHA handling are outside v1 scope.
