# syntax=docker/dockerfile:1.7
FROM node:22.14.0-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.12.10-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    LLM_AUTH_DB=/data/app.sqlite3 \
    LLM_AUTH_MASTER_KEY_FILE=/run/secrets/master_key \
    LLM_AUTH_LOCK_FILE=/data/browser.lock \
    LLM_AUTH_SECURE_COOKIE=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends novnc tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bridge && useradd --uid 10001 --gid bridge --create-home bridge \
    && mkdir /data && chown bridge:bridge /data
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.22
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project
ENV PATH=/app/.venv/bin:$PATH
USER bridge
ENTRYPOINT ["/usr/bin/tini", "--"]

FROM base AS app
COPY app/ ./app/
COPY --from=frontend /build/dist/ ./frontend/dist/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12.10-slim-bookworm AS gost
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && case "$TARGETARCH" in \
       amd64) GOST_SHA=e0e3a2c9116e2f025e962bba340749f80696bda318613d45e5ae96dd0bcae37c ;; \
       arm64) GOST_SHA=c58af4a74362a95caa7f580817ad624497d192dfeb60468dc8a4c70c293c6b01 ;; \
       *) echo "Unsupported GOST architecture" >&2; exit 1 ;; esac \
    && curl -fsSL "https://github.com/go-gost/gost/releases/download/v3.3.1/gost_3.3.1_linux_${TARGETARCH}.tar.gz" -o /tmp/gost.tar.gz \
    && echo "$GOST_SHA  /tmp/gost.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/gost.tar.gz -C /usr/local/bin gost \
    && rm /tmp/gost.tar.gz

FROM base AS worker
USER root
COPY --from=gost /usr/local/bin/gost /usr/local/bin/gost
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright XDG_CACHE_HOME=/opt/cache DISPLAY=:99
RUN apt-get update && apt-get install -y --no-install-recommends tigervnc-standalone-server openbox x11-utils websockify libgtk-3-0 libasound2 \
    && mkdir -p /opt/playwright /opt/cache \
    && chown bridge:bridge /opt/playwright /opt/cache \
    && chmod u+rwx,go+rx /opt/playwright /opt/cache \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project --extra browser
RUN umask 022 \
    && XDG_CACHE_HOME=/opt/cache /app/.venv/bin/python -m camoufox fetch \
    && chown -R bridge:bridge /opt/playwright /opt/cache \
    && chmod -R u+rwX,go+rX /opt/playwright /opt/cache
RUN <<'SH'
cat > /usr/local/bin/bridge-worker <<'SCRIPT'
#!/bin/sh
set -eu
Xtigervnc :99 -geometry 1920x1080 -depth 24 -rfbport 5900 -localhost -SecurityTypes None -AlwaysShared -AcceptSetDesktopSize=1 -nolisten tcp &
vnc_pid=$!
# Wait for the local display before starting the window manager.
n=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
  n=$((n+1)); [ "$n" -lt 100 ] || exit 1
  sleep 0.1
done
openbox --sm-disable &
wm_pid=$!
n=0
while ! xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id'; do
  n=$((n+1)); [ "$n" -lt 100 ] || exit 1
  sleep 0.1
done
websockify 0.0.0.0:6080 localhost:5900 &
web_pid=$!
python -m app.worker &
worker_pid=$!
cleanup() {
  trap - TERM INT EXIT
  kill "$worker_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
  kill "$web_pid" "$wm_pid" "$vnc_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT
wait "$worker_pid"
SCRIPT
chmod 755 /usr/local/bin/bridge-worker
SH
# Keep source changes after browser/system dependencies so CI can reuse those layers.
COPY app/ ./app/
COPY --from=frontend /build/dist/ ./frontend/dist/
USER bridge
EXPOSE 6080
CMD ["bridge-worker"]
