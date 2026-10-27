# CLIProxyAPI native OAuth extension

This source overlay adds the bridge-managed Codex OAuth session protocol to the
native CLIProxyAPI v8 management API. Public upstream source is pinned by
`UPSTREAM_REVISION`; `source.json` records the reviewed extension revision and
patch SHA-256. `upstream.patch.sha256` verifies the complete source delta, including
synthetic regression tests and the upstream `docs/bridge-oauth-v8.md` contract.
Current acceptance is tracked in the [roadmap](../../docs/roadmap.md).

## Hosted validation and rebuilding

Use `.github/workflows/validation.yml` on a GitHub-hosted runner. The `cpa` job
checks out the exact public upstream commit, verifies the patch checksum, checks
and applies the patch, installs the toolchain requested by the pinned `go.mod`,
runs `go test ./...`, then compiles `go build ./cmd/server`. Keep module downloads,
build caches and executables on the runner; retrieve only required evidence and
artifacts. The workflow does not deploy a running service. Successful
synthetic tests do not establish live account, runtime reload or deployment health.
Do not run compilation or executable test suites on the controller.

The general bridge image build does not implicitly modify a running CLIProxyAPI
installation. The [CPA native image workflow](../../.github/workflows/cpa-native-image.yml)
runs the overlay build on GitHub-hosted runners and publishes an immutable GHCR
tag plus its digest. Deployments must consume that digest; production hosts must
not compile the source or pull the upstream `latest` image. Preserve the current native configuration,
auth-directory volume and management bearer authentication. Keep credentials and
session state outside source control; never copy real auth files into a build.

## Contract and recovery

Use the [CLIProxyAPI contract](../../docs/contracts/integrations/cliproxyapi.md)
for protocol selection, bridge responsibilities, and the pinned original server
contract. See the [deployment guide](../../docs/guides/deployment.md) for upgrade
and recovery requirements and the [roadmap](../../docs/roadmap.md) for acceptance.
Back up the native configuration and complete auth-directory before upgrading;
retain `auth-dir/.bridge-oauth` with the credential volume as secret material.
