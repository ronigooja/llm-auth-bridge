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
RUN pip install --no-cache-dir uv==0.8.22 && uv sync --frozen --no-dev --no-install-project
ENV PATH=/app/.venv/bin:$PATH
COPY app/ ./app/
COPY --from=frontend /build/dist/ ./frontend/dist/
USER bridge
ENTRYPOINT ["/usr/bin/tini", "--"]

FROM base AS app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
USER root
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
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright DISPLAY=:99
RUN apt-get update && apt-get install -y --no-install-recommends xvfb x11vnc websockify \
    && pip install --no-cache-dir playwright==1.56.0 \
    && /usr/local/bin/playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright \
    && rm -rf /var/lib/apt/lists/*
# The uv environment also installs the exact browser API version for runtime imports.
RUN uv sync --frozen --no-dev --no-install-project --extra browser
RUN <<'SH'
cat > /usr/local/bin/bridge-worker <<'SCRIPT'
#!/bin/sh
set -eu
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
xvfb_pid=$!
# Wait for the local display socket before connecting the VNC server.
n=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
  n=$((n+1)); [ "$n" -lt 100 ] || exit 1
  sleep 0.1
done
x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -nopw -quiet &
vnc_pid=$!
websockify 0.0.0.0:6080 localhost:5900 &
web_pid=$!
python -m app.worker &
worker_pid=$!
cleanup() {
  trap - TERM INT EXIT
  kill "$worker_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
  kill "$web_pid" "$vnc_pid" "$xvfb_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT
wait "$worker_pid"
SCRIPT
chmod 755 /usr/local/bin/bridge-worker
SH
USER bridge
EXPOSE 6080
CMD ["bridge-worker"]
