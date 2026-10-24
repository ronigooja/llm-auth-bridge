# Build the binary with build.sh first; use an immutable upstream runtime image.
ARG VOICE_BASE_IMAGE
FROM ${VOICE_BASE_IMAGE}
ARG BRIDGE_PATCH_SHA256
LABEL org.opencontainers.image.description="ChatGPT Web Voice with bridge-v1 compatibility" \
      io.llm-auth-bridge.upstream="6338ac478070aaa34bfe7a3c0469caf9e9174c02" \
      io.llm-auth-bridge.patch-sha256="${BRIDGE_PATCH_SHA256}"
COPY --chmod=0755 server /app/server
# Preserve the upstream runtime user, curl-impersonate, CA bundle and defaults.
