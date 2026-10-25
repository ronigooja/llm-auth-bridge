# CLIProxyAPI native OAuth extension

This source overlay adds the bridge-managed Codex OAuth session protocol to the
native CLIProxyAPI v8 management API. Public upstream source is pinned by
`UPSTREAM_REVISION`; `source.json` records the reviewed extension revision and
patch SHA-256. `upstream.patch.sha256` verifies the complete source delta, including
synthetic regression tests and the upstream `docs/bridge-oauth-v8.md` contract.
Real provider account verification remains **unverified**.

## Hosted validation and rebuilding

Use `.github/workflows/validation.yml` on a GitHub-hosted runner. The `cpa` job
checks out the exact public upstream commit, verifies the patch checksum, checks
and applies the patch, installs the toolchain requested by the pinned `go.mod`,
runs `go test ./...`, then compiles `go build ./cmd/server`. Keep module downloads,
build caches and executables on the runner; retrieve only required evidence and
artifacts. The workflow does not build or deploy a container image. Successful
synthetic tests do not establish live account, runtime reload or deployment health.
Do not run compilation or executable test suites on the controller.

The general bridge image build does not implicitly modify a running CLIProxyAPI
installation. Apply this source overlay in the authorized remote build environment,
then deploy the resulting native executable or image through the existing
CLIProxyAPI deployment process. Preserve the current native configuration,
auth-directory volume and management bearer authentication. Keep credentials and
session state outside source control; never copy real auth files into a build.

## Management and persistence

All extension routes live under `/v8/management/bridge/oauth` and require the
existing management bearer authentication. Only the native file token store is
supported. The bridge verifies `cpa-native-oauth-v1` capabilities before use and
uses durable create/read/callback/commit/cancel session operations. Token exchange
and credential writes stay inside CLIProxyAPI; the bridge does not import tokens.
See the patched `docs/bridge-oauth-v8.md` for exact fields, states and readback
semantics.

Back up the native configuration and complete auth-directory before upgrading.
The extension persists restricted secret session state under
`auth-dir/.bridge-oauth`, which must remain with the credential volume across
restarts. Treat that directory as credential material. Its contents are excluded
from the normal auth-record scanner. Completed writes update native credential
records and preserve unrelated settings; direct/proxy routing is explicit. A lost
exchange response requires a fresh session; a lost commit response is reconciled
through the existing session, without replaying token exchange or rolling back a
newer credential. Disk readback verifies identity, route, remote ID and token
digest; provider acceptance remains a separate serial operator check.
