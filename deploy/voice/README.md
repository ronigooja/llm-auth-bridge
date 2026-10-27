# Voice bridge-v1 gateway fork

This overlay implements the bridge management API in the native Go gateway from
Space3044/chatgpt-web-voice at `6338ac478070aaa34bfe7a3c0469caf9e9174c02`.
The reviewed source delta is `bridge-v1.patch`; its checksum is recorded beside it.
See the [roadmap](../../docs/roadmap.md) for the distinction between synthetic
checks, assisted credential synchronization, and provider acceptance.

## Build

Requirements: Git, SHA-256 utilities, a Go toolchain compatible with the pinned
upstream `go.mod` and Docker. Module dependencies are pinned by upstream `go.sum`.
Use the existing upstream runtime image built from the pinned revision, preferably
an immutable registry digest or a recorded local image ID. It supplies the existing
curl-impersonate runtime, static assets, CA bundle, nonroot user and environment.
The overlay replaces only `/app/server`.

```sh
./deploy/voice/build.sh /tmp/voice-bridge-build \
  'registry.example/voice@sha256:REPLACE_WITH_VERIFIED_RUNTIME_IMAGE_DIGEST' \
  llm-auth-bridge/voice:bridge-v1
```

The script creates a fresh output directory, checks the patch checksum, checks out
the exact upstream revision, applies the patch, runs all Go tests and builds a
static Linux server before constructing the overlay image. Set `GOARCH` explicitly
for cross builds; the runtime image architecture must match. A preexisting output
directory is rejected. Build output and cloned sources should stay outside Git.
For an offline rebuild, make the pinned Git commit and Go module cache available
locally and perform the same checkout, patch verification, tests and build steps.

For an already tested local source checkout, reuse its Go cache and build binary
with the same command above, then build this Dockerfile with a context containing
only `server` and `Dockerfile`; include the actual patch SHA-256 as the label arg.
Do not use the original upstream Dockerfile merely to replace an already available
runtime image: that downloads curl-impersonate and repeats unrelated layers.

## Contract and recovery

Use the [Voice contract](../../docs/contracts/integrations/voice.md) for the pinned
original server contract, bridge constraints, and disposable HTTP acceptance.
Follow the [deployment guide](../../docs/guides/deployment.md) for upgrading an
existing gateway and restoring its matching database, key, and image. Retain the
existing runtime volume, UID, network and hardening settings. Do not point the
synthetic acceptance harness at a populated production database. Current
acceptance and open verification are maintained in the [roadmap](../../docs/roadmap.md).
