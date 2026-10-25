# Native OAuth and browser identity validation

## Tested inputs and environment

GitHub-hosted validation ran on 2026-10-25 against bridge revision
`bf744aa5a3c7f867d9e57ab392af9933cbf3c280` on
`validation/native-oauth-browser-identity`:
[run 40218832546](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40218832546).
The workflow completed with **failure**, not an overall passing verdict.
The controller checkout had no uncommitted source inputs. Job recorder files list
only the generated `?? validation-logs/` evidence directory; that directory is
created before recording status and is not an uncommitted source change.

All executable validation ran on GitHub-hosted `ubuntu-24.04` Linux X64 runners.
Configured runtimes were Python 3.12, Node 22.14.0, uv 0.8.22 and the upstream
`go.mod` toolchain; Go logs report `go1.26.10 linux/amd64`. The controller performed
source/static checks, Git operations and evidence collection only. No local
compilation, executable test suite, Docker build, provider login or deployment ran.

The native inputs were the complete checked-in `deploy/cpa/upstream.patch`:

- Public upstream: `https://github.com/router-for-me/CLIProxyAPI.git`.
- Upstream revision: `07b5a7a1ca267c5d9b743e38dff4ed8ff1da0c91`.
- Native extension revision: `950873b44d1e03ae367472828a5b9aa81aeeffe7`.
- Patch SHA-256: `69592287dda1f727f862abde10ca2291b1ee210c0d453cb6b057ddbf72d367a8`.

CI verified the committed checksum, fetched the exact upstream revision, checked
and applied the full patch. `upstream-input-changes.txt` is a supplemental tracked
file diff summary: Git does not include the newly created, untracked handler,
regression test and documentation files in that summary. The complete verified
patch and `source.json` describe the actual input, including those new files.
The baseline job checked out the same public upstream revision without applying
the patch; its upstream uncommitted-input record is empty.

## Actual results

| Scope / exact command | Exit | Observed result |
| --- | --- | --- |
| Synthetic prerequisites, including verified GOST and Playwright Chromium | 0 | Provisioned successfully |
| `npm test --prefix frontend` | 0 | 38 tests passed across 3 files |
| `npm run build --prefix frontend` | 0 | TypeScript check and Vite production build passed |
| `uv run pytest -ra --junitxml=validation-logs/pytest.xml` | 0 | 251 passed, 1 skipped, 4 warnings; 188.45 seconds |
| `go test -count=1 ./internal/api/handlers/management ./internal/api` | 0 | Native management and API packages passed |
| Patched upstream: `go test -count=1 ./...` | 1 | Full suite failed; details below |
| Patched upstream: `go build ./cmd/server` | 0 | Native server executable compiled after the full-suite failure |
| Untouched upstream: `go test -count=1 ./...` | 1 | Full baseline suite failed; details below |

Pytest's sole skip was
`tests/test_voice_bridge_acceptance.py::test_disposable_voice_bridge_real_http_contract`:
`set BRIDGE_VOICE_ACCEPTANCE_URL for a disposable synthetic server`. A separate
Voice server acceptance deployment was not provisioned. Chromium and all three
synthetic proxy protocol prerequisites were available for the executed suite.

The initial run
[40218282256](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40218282256)
at revision `42fc085f169ee40d1cd34aad869e4a5c6290497c` failed all 29 browser-dependent
cases because Ubuntu AppArmor blocked Chromium user namespaces (`No usable
sandbox`). The final workflow enables user namespaces only on its ephemeral
runner with
`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.
Chromium sandboxing remains enabled; no production launch policy or test
assertion was weakened. Final browser-dependent tests passed.

## Full upstream Go failures

The untouched baseline and patched full suites both failed these unmodified
upstream tests:

- `internal/home`: `TestClusterBalanceBlockedRPCDoesNotDelayHeartbeatExpiry`,
  including `ENABLE`, `CLAIM`, `PING` and `RESULT` subtests. Each reached the
  two-second heartbeat-expiry/subscriber-shutdown wait limit.
- `internal/store`: `TestGitTokenStoreFullPackfileCorruptionFailsClosedWithDirtyManagedFile`
  (`config` and `auth`), `TestGitTokenStoreMissingPackfileRecoveryFailsClosedWithoutBaseline`,
  and `TestInspectRecoveryBaselineFailureClosesRepositoryHandle`.
  These assertions expected repository-corruption classification after packfile
  deletion/corruption but observed nil or a different packfile error.

The patched suite additionally failed
`sdk/api/handlers/openai::TestResponsesLateInterruptDoesNotPoisonNextCreate` at
`openai_responses_late_interrupt_test.go:147`: a five-second loopback WebSocket
read timed out while awaiting the error response for an unknown interrupt.
The same test passed in the concurrent untouched baseline and in the initial
patched full run. Its source is unchanged by this patch. This observation alone
does not establish the cause or prove absence of a regression. The two final
full-suite failure sets therefore **do not match**, and no all-upstream-tests-pass
or no-new-failures claim is made. No unrelated upstream code or test expectations
were changed to suppress these failures.

## Bounded timeout diagnostic

A separate workflow-only revision,
`a843bb362e2efcf192957f6699a6960a28fcd47b`, left the tested product source unchanged
and added a diagnostic branch. The
[diagnostic run 40219551648](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40219551648)
on `validation/upstream-late-interrupt` completed successfully. It reran only:

```sh
go test -count=20 -run '^TestResponsesLateInterruptDoesNotPoisonNextCreate$' ./sdk/api/handlers/openai
```

The untouched baseline and checksum-verified patched source both exited 0 for all
20 repetitions (reported package times 0.051 and 0.093 seconds respectively).
Source provisioning also exited 0 for both jobs. Both used the same public pin
and Go 1.26.10; controller and baseline source-status records were empty. The
bridge, full Go suites and image builds did not rerun in this diagnostic.

The isolated repeat did not reproduce the observed timeout. It does not establish
its cause, prove non-regression, change the recorded full-suite failure sets, or
turn the full validation run into a success.

## Saved evidence

The complete downloaded evidence is in
`/tmp/native-validation-evidence-bf744aa/` on the controller. Its root contains
`run.json`, `jobs.json`, `artifacts.json`, controller source/status records, the
three original ZIP files, and `go-baseline-comparison.json`. Logs include traced
commands and separate `.exit` files; pytest JUnit output is retained.

| Artifact | GitHub artifact ID | Downloaded ZIP | Extracted directory below evidence root |
| --- | --- | --- | --- |
| Bridge | `12608835612` | `12608835612.zip` | `bridge-validation-bf744aa5a3c7f867d9e57ab392af9933cbf3c280/` |
| Patched CPA | `12609265649` | `12609265649.zip` | `cpa-validation-bf744aa5a3c7f867d9e57ab392af9933cbf3c280/` |
| Untouched CPA | `12609505068` | `12609505068.zip` | `cpa-baseline-bf744aa5a3c7f867d9e57ab392af9933cbf3c280/` |

Bridge logs are `provision.log`, `frontend.log`, `pytest.log` and `pytest.xml`.
Patched CPA logs are `source.log`, `go-management.log`, `go.log` and
`go-build.log`; baseline logs are `source.log` and `go.log`. All corresponding
step exit files were collected. Artifact retention is seven days; GitHub reports
expiry on 2026-11-01 between 17:59 and 18:00 UTC. Downloaded controller copies
remain available independently of GitHub artifact expiry. Initial-run evidence
is retained separately in `/tmp/native-validation-evidence-42fc085/`.

Diagnostic evidence is saved in `/tmp/native-interrupt-evidence-a843bb3/`, with
run/jobs/artifacts metadata, source/status records and both original ZIP files:

| Diagnostic artifact | GitHub artifact ID / ZIP | Extracted directory below diagnostic evidence root |
| --- | --- | --- |
| Untouched source, 20 repetitions | `12608379597` / `12608379597.zip` | `cpa-interrupt-baseline-a843bb362e2efcf192957f6699a6960a28fcd47b/` |
| Patched source, 20 repetitions | `12609525984` / `12609525984.zip` | `cpa-interrupt-patched-a843bb362e2efcf192957f6699a6960a28fcd47b/` |

Each diagnostic directory contains `source.log`, `source.exit`, `go.log`,
`go.exit`, runtime/source metadata and the upstream changed-input record. GitHub
reports diagnostic artifact expiry on 2026-11-01 at 18:05:55 and 18:06:16 UTC.

These checks establish the recorded synthetic bridge behavior, focused native
API tests and Linux server compilation. Real-account usability, deployment,
runtime credential reload completion and Apple platform behavior remain
unverified.
