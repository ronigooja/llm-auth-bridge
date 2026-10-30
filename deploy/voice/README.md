# Voice bridge-v1 gateway fork

The bridge-v1 management API is implemented in the maintained
[ronigooja/chatgpt-web-voice fork](https://github.com/ronigooja/chatgpt-web-voice)
at the immutable revision recorded in [source.json](source.json). The old local
`bridge-v1.patch` overlay is retained only as historical evidence; do not apply
it to the fork, because doing so duplicates the API and can produce a broken
binary.
See the [roadmap](../../docs/roadmap.md) for the distinction between synthetic
checks, assisted credential synchronization, and provider acceptance.

## Build

Requirements: Git, SHA-256 utilities, a Go toolchain compatible with the pinned
upstream `go.mod` and Docker. Module dependencies are pinned by upstream `go.sum`.
The resulting image must be published by the voice image workflow and deployed by
digest. The human-readable tag in `source.json` is for discovery only; record the
workflow's OCI digest in the release record before installation.

```sh
./deploy/voice/build.sh /tmp/voice-bridge-build \
  llm-auth-bridge/voice:bridge-v1-e6001bc
```

The script creates a fresh output directory, checks out the exact fork revision,
runs the fork's Go tests, builds the static server, and builds the fork's Docker
image. A preexisting output directory is rejected. Build output and cloned sources
must stay outside Git. The workflow also records the source revision, image digest,
SBOM, and provenance. Do not substitute a mutable `main` tag.

## Install, upgrade, and rollback

Install the digest-pinned image with the existing gateway data mount, encryption
key, network, UID, and hardening settings. Run the disposable HTTP acceptance
before connecting Zoe or a production account store. For an upgrade, stop the
gateway, back up its SQLite database and sidecars, deploy the new digest, and run
the acceptance against a separate empty database. Rollback restores the previous
image digest **and its matching database/key pair**; an image-only rollback is
unsafe. Keep both image records until the new release is accepted.

## Contract and recovery

Use the [Voice contract](../../docs/contracts/integrations/voice.md) for the pinned
original server contract, bridge constraints, and disposable HTTP acceptance.
Follow the [deployment guide](../../docs/guides/deployment.md) for gateway
installation and recovery. Retain the existing runtime volume, UID, network and
hardening settings. Do not point the synthetic acceptance harness at a populated
production database. Current
acceptance and open verification are maintained in the [roadmap](../../docs/roadmap.md).
