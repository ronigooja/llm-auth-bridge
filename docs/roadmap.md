# Capabilities and remaining acceptance

This is the authority for capability status and outstanding verification. The
status below was last consolidated on 2026-10-27 against source baseline
[`d22cdb8`](https://github.com/ronigooja/llm-auth-bridge/tree/d22cdb8034f736aa4deca6a08de87dbc64f30435).
Implementation, synthetic acceptance, assisted real-account observations and
unattended operation are distinct. A management connection or stored credential
readback does not prove provider usability, runtime reload, or actual egress.

Detailed dated provenance is in the [evidence log](evidence/2026-10-27-acceptance.md).

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

## Later scope

Other vendors, IMAP, concurrent browser scheduling, multi-user authorization,
multi-host queues and automated CAPTCHA handling are outside v1 scope.
