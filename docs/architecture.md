# Architecture

The app service owns the HTTP API, SQLite metadata, task leases, and administrator controls. A separate worker consumes queued tasks and will host Chromium, Xvfb, x11vnc, and noVNC. Each account has an independent browser profile and encrypted secret fields. The master key is mounted from a secret file and is never stored in SQLite.

Tasks are durable records with `queued`, `running`, `waiting_human`, `sync_pending`, `succeeded`, `failed`, and `cancelled` states. A worker heartbeat and lease prevent duplicate execution; restart recovery marks an in-flight browser task interrupted instead of replaying an authorization exchange.

Vendor adapters produce typed credentials (`codex_oauth` or `chatgpt_web`). Downstream adapters validate and synchronize those credentials without sharing browser proxy configuration.

