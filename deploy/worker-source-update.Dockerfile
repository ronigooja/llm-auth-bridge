# Source-only fallback for a previously verified, unchanged worker runtime.
# Tag the exact immutable runtime image locally and verify its ID before building.
# See docs/deployment.md for the required source/dependency checks.
FROM node:22.14.0-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM llm-auth-bridge/worker-base:sha256-b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380@sha256:b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION \
      org.llm-auth-bridge.runtime-base="sha256:b289e357a94d091da6da2ec69c0f3e92019a85978d2bf06f0dff679e80d94380"
COPY --chown=bridge:bridge app/ /app/app/
COPY --chown=bridge:bridge --from=frontend /build/dist/ /app/frontend/dist/
