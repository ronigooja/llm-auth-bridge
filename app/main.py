"""Authenticated HTTP boundary. Initialization is exclusively an offline CLI action."""

from contextlib import asynccontextmanager
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .crypto import load_key, encrypt, decrypt
from .db import database, validate_database
from .models import (
    AccountCreate,
    AccountPatch,
    TargetBody,
    LoginBody,
    PasswordBody,
    ImportBody,
    TaskBody,
    LoginFlowBody,
    BrowserBody,
    CodeBody,
    SettingsBody,
    DiscardBody,
    public_url,
)
from .importer import preview, parse_line
from .queue import Queue, Conflict, NotFound, public_task, event

HASHER = PasswordHasher()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_account(conn, row):
    fields = (
        "id",
        "username",
        "status",
        "route_type",
        "version",
        "created_at",
        "updated_at",
        "allow_http_mailbox",
    )
    result = {k: row[k] for k in fields}
    result.update(
        {
            f"has_{k}": bool(row[c])
            for k, c in (
                ("password", "password_cipher"),
                ("totp", "totp_cipher"),
                ("mailbox", "mailbox_url_cipher"),
            )
        }
    )
    result["target_ids"] = [
        r[0]
        for r in conn.execute(
            "SELECT target_id FROM account_targets WHERE account_id=?", (row["id"],)
        )
    ]
    return result


def public_target(row, key):
    config = json.loads(decrypt(row["config_cipher"], key))
    return {
        **{
            k: row[k]
            for k in ("id", "kind", "name", "version", "verification", "created_at")
        },
        "config": {
            k: config[k]
            for k in ("base_url", "allow_http", "compatibility")
            if k in config
        },
    }


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        key = load_key(settings.key_file)
        validate_database(settings.db_path, key)
        app.state.key = key
        app.state.queue = Queue(settings, key)
        yield

    app = FastAPI(
        title="LLM Auth Bridge",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    def session(cookie):
        if not cookie:
            return None
        with database(settings.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                (digest(cookie), time.time()),
            ).fetchone()
            return dict(row) if row else None

    def same_origin(headers):
        origin = headers.get("origin")
        if not origin:
            return True
        try:
            u = urlsplit(origin)
            return u.scheme in ("http", "https") and u.netloc == headers.get("host")
        except ValueError:
            return False

    @app.middleware("http")
    async def protect(request, call_next):
        path = request.url.path
        if (
            request.headers.get("content-length", "0").isdigit()
            and int(request.headers.get("content-length", "0")) > 2_100_000
        ):
            return JSONResponse({"detail": "request is too large"}, 413)
        if path.startswith("/api/") or path.startswith("/novnc"):
            if path != "/api/v1/auth/login":
                auth = session(request.cookies.get("bridge_session"))
                if not auth:
                    return JSONResponse({"detail": "authentication required"}, 401)
                request.state.auth = auth
                if request.method not in ("GET", "HEAD", "OPTIONS") and (
                    not same_origin(request.headers)
                    or not secrets.compare_digest(
                        request.headers.get("x-csrf-token", ""), auth["csrf"]
                    )
                ):
                    return JSONResponse({"detail": "CSRF validation failed"}, 403)
            elif request.method == "POST" and not same_origin(request.headers):
                return JSONResponse({"detail": "origin validation failed"}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if path.startswith(("/api/", "/novnc")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "invalid request fields"}, 422)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(
            {"detail": "invalid configuration or unreadable encrypted data"}, 422
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request, exc):
        return JSONResponse(
            {"detail": "duplicate record or conflicting reference"}, 409
        )

    @app.exception_handler(sqlite3.DatabaseError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "database operation failed"}, 503)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, 404)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            validate_database(settings.db_path, app.state.key)
        except Exception:
            raise HTTPException(503, "not ready") from None
        return {"status": "ready"}

    @app.post("/api/v1/auth/login")
    def login(body: LoginBody, request: Request):
        client = digest(request.client.host if request.client else "unknown")
        now = time.time()
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = conn.execute(
                "SELECT * FROM login_attempts WHERE client=?", (client,)
            ).fetchone()
            if attempt and attempt["reset_at"] > now and attempt["attempts"] >= 5:
                raise HTTPException(
                    429,
                    "too many login attempts",
                    headers={
                        "Retry-After": str(max(1, int(attempt["reset_at"] - now)))
                    },
                )
            count = (
                attempt["attempts"] + 1 if attempt and attempt["reset_at"] > now else 1
            )
            reset = (
                attempt["reset_at"]
                if attempt and attempt["reset_at"] > now
                else now + 300
            )
            conn.execute(
                "INSERT OR REPLACE INTO login_attempts(client,attempts,reset_at) VALUES(?,?,?)",
                (client, count, reset),
            )
            admin = conn.execute(
                "SELECT password_hash FROM admin WHERE id=1"
            ).fetchone()
        try:
            valid = bool(admin) and HASHER.verify(admin["password_hash"], body.password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise HTTPException(401, "invalid administrator password")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT password_hash FROM admin WHERE id=1"
            ).fetchone()
            if not current or current[0] != admin["password_hash"]:
                raise HTTPException(401, "administrator password changed; log in again")
            conn.execute("DELETE FROM login_attempts WHERE client=?", (client,))
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
            conn.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (digest(token), csrf, now + settings.session_seconds),
            )
        response = JSONResponse({"csrf_token": csrf})
        response.set_cookie(
            "bridge_session",
            token,
            httponly=True,
            secure=settings.secure_cookie,
            samesite="strict",
            max_age=settings.session_seconds,
            path="/",
        )
        return response

    @app.get("/api/v1/auth/session")
    def current(request: Request):
        return {"csrf_token": request.state.auth["csrf"]}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request):
        with database(settings.db_path) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (request.state.auth["token_hash"],),
            )
        response = JSONResponse({"logged_out": True})
        response.delete_cookie("bridge_session", path="/")
        return response

    @app.post("/api/v1/auth/password")
    def password(body: PasswordBody):
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            admin = conn.execute("SELECT password_hash FROM admin").fetchone()
            try:
                valid = HASHER.verify(admin[0], body.current_password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid:
                raise HTTPException(401, "invalid administrator password")
            conn.execute(
                "UPDATE admin SET password_hash=?", (HASHER.hash(body.new_password),)
            )
            conn.execute("DELETE FROM sessions")
        response = JSONResponse({"changed": True})
        response.delete_cookie("bridge_session", path="/")
        return response

    def get_row(conn, table, id):
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
        if not row:
            raise NotFound("resource not found")
        return row

    def check_native_busy(conn, column, id):
        if conn.execute(
            f"SELECT 1 FROM tasks t JOIN native_sessions n ON n.task_id=t.id "
            f"WHERE t.{column}=? AND t.state IN ('queued','running','waiting_human','sync_pending')",
            (id,),
        ).fetchone():
            raise Conflict("resource has an unresolved native authorization task")

    def check_busy(conn, column, id, include_queued=False):
        check_native_busy(conn, column, id)
        states = (
            "'queued','running','waiting_human','sync_pending'"
            if include_queued
            else "'running','waiting_human','sync_pending'"
        )
        if conn.execute(
            f"SELECT 1 FROM tasks WHERE {column}=? AND state IN ({states})", (id,)
        ).fetchone():
            raise Conflict("resource has an active task")

    def bind(conn, account_id, target_ids):
        ids = set(target_ids or [])
        for id in ids:
            get_row(conn, "targets", id)
        conn.execute("DELETE FROM account_targets WHERE account_id=?", (account_id,))
        conn.executemany(
            "INSERT INTO account_targets VALUES(?,?)", [(account_id, i) for i in ids]
        )

    @app.get("/api/v1/accounts")
    def accounts():
        with database(settings.db_path) as conn:
            return {
                "accounts": [
                    public_account(conn, r)
                    for r in conn.execute("SELECT * FROM accounts ORDER BY id")
                ]
            }

    def save_account(body, account_id=None):
        key = app.state.key
        values = body.model_dump(exclude_unset=True)
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = dict(get_row(conn, "accounts", account_id)) if account_id else None
            if old:
                check_busy(conn, "account_id", account_id)
            if (
                values.get("username")
                and conn.execute(
                    "SELECT 1 FROM accounts WHERE username=? COLLATE NOCASE AND id!=?",
                    (values["username"], account_id or -1),
                ).fetchone()
            ):
                raise Conflict("account already exists")
            if values.get("username", "") is None or (
                "password" in values and values["password"] is None
            ):
                raise HTTPException(
                    422, "required secret or identity cannot be cleared"
                )
            allow = values.get(
                "allow_http_mailbox", old["allow_http_mailbox"] if old else False
            )
            if allow is None:
                raise HTTPException(422, "invalid mailbox policy")
            mailbox = values.get(
                "mailbox_url",
                decrypt(old["mailbox_url_cipher"], key)
                if old and old["mailbox_url_cipher"]
                else None,
            )
            if mailbox:
                public_url(mailbox, allow)
            route = values.get("route_type", old["route_type"] if old else "unset")
            proxy = values.get(
                "proxy",
                json.loads(decrypt(old["proxy_cipher"], key))
                if old and old["proxy_cipher"]
                else None,
            )
            if isinstance(values.get("proxy"), dict) and old and old["proxy_cipher"]:
                proxy = {
                    **json.loads(decrypt(old["proxy_cipher"], key)),
                    **values["proxy"],
                }
            if route is None:
                raise HTTPException(422, "invalid route")
            if route == "proxy" and not proxy:
                raise HTTPException(422, "proxy configuration required")
            columns = {}
            for field, column in [
                ("username", "username"),
                ("password", "password_cipher"),
                ("totp", "totp_cipher"),
                ("mailbox_url", "mailbox_url_cipher"),
            ]:
                if field in values:
                    columns[column] = (
                        encrypt(values[field], key)
                        if values[field] and field != "username"
                        else values[field]
                    )
            columns.update(
                route_type=route,
                proxy_cipher=encrypt(json.dumps(proxy), key)
                if route == "proxy"
                else None,
                allow_http_mailbox=int(allow),
            )
            if old:
                conn.execute(
                    "UPDATE accounts SET "
                    + ",".join(f"{k}=?" for k in columns)
                    + ",version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (*columns.values(), account_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO accounts("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    tuple(columns.values()),
                )
                account_id = cur.lastrowid
            if "target_ids" in values:
                bind(conn, account_id, values["target_ids"])
            return public_account(conn, get_row(conn, "accounts", account_id))

    @app.post("/api/v1/accounts")
    def create_account(body: AccountCreate):
        return save_account(body)

    @app.patch("/api/v1/accounts/{account_id}")
    def patch_account(account_id: int, body: AccountPatch):
        return save_account(body, account_id)

    @app.delete("/api/v1/accounts/{account_id}")
    def delete_account(account_id: int):
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            get_row(conn, "accounts", account_id)
            check_busy(conn, "account_id", account_id, True)
            conn.execute("DELETE FROM tasks WHERE account_id=?", (account_id,))
            conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        return {"deleted": True}

    def import_records(text):
        with database(settings.db_path) as conn:
            existing = {
                r[0].casefold() for r in conn.execute("SELECT username FROM accounts")
            }
        records = preview(text)
        for row in records:
            if row.get("account", "").casefold() in existing:
                row.update(valid=False, duplicate=True, error="account already exists")
            if row.get("valid"):
                try:
                    parsed = parse_line(text.splitlines()[row["line"] - 1])
                    AccountCreate(
                        username=parsed.username,
                        password=parsed.password,
                        totp=parsed.totp,
                        mailbox_url=parsed.mailbox_url,
                    )
                    if parsed.mailbox_url:
                        public_url(parsed.mailbox_url)
                except ValueError:
                    row.update(
                        valid=False, error="invalid account secrets or mailbox URL"
                    )
        return records

    @app.post("/api/v1/import/preview")
    def import_preview(body: ImportBody):
        return {"records": import_records(body.text)}

    @app.post("/api/v1/import/confirm")
    def import_confirm(body: ImportBody):
        records = import_records(body.text)
        if not records or any(not r["valid"] for r in records):
            raise HTTPException(422, "import contains invalid or duplicate records")
        imported = []
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = {
                r[0].casefold() for r in conn.execute("SELECT username FROM accounts")
            }
            for line in body.text.splitlines():
                if not line.strip():
                    continue
                r = parse_line(line)
                if r.username.casefold() in existing:
                    raise Conflict("account already exists")
                existing.add(r.username.casefold())
                conn.execute(
                    "INSERT INTO accounts(username,password_cipher,totp_cipher,mailbox_url_cipher) VALUES(?,?,?,?)",
                    (
                        r.username,
                        encrypt(r.password, app.state.key),
                        encrypt(r.totp, app.state.key),
                        encrypt(r.mailbox_url, app.state.key)
                        if r.mailbox_url
                        else None,
                    ),
                )
                imported.append(r.username)
        return {"imported": imported}

    @app.get("/api/v1/targets")
    def targets():
        with database(settings.db_path) as conn:
            return {
                "targets": [
                    public_target(r, app.state.key)
                    for r in conn.execute("SELECT * FROM targets ORDER BY id")
                ]
            }

    @app.post("/api/v1/targets")
    def create_target(body: TargetBody):
        with database(settings.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO targets(kind,name,config_cipher) VALUES(?,?,?)",
                (body.kind, body.name, encrypt(json.dumps(body.config), app.state.key)),
            )
            return public_target(get_row(conn, "targets", cur.lastrowid), app.state.key)

    @app.patch("/api/v1/targets/{target_id}")
    def patch_target(target_id: int, body: dict):
        if set(body) - {"kind", "name", "config"}:
            raise HTTPException(422, "invalid target fields")
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = get_row(conn, "targets", target_id)
            native_tasks = conn.execute(
                "SELECT t.id,t.state,t.phase,t.execution_id FROM tasks t "
                "JOIN native_sessions n ON n.task_id=t.id WHERE t.target_id=? "
                "AND t.state IN ('queued','running','waiting_human','sync_pending')",
                (target_id,),
            ).fetchall()
            if conn.execute(
                "SELECT 1 FROM tasks WHERE target_id=? AND (state IN ('running','waiting_human') OR (state='sync_pending' AND execution_id IS NOT NULL))",
                (target_id,),
            ).fetchone():
                raise Conflict("target has an executing task")
            oldconfig = json.loads(decrypt(old["config_cipher"], app.state.key))
            if old["kind"] == "cliproxyapi":
                oldconfig.setdefault("compatibility", None)
            if "config" in body and not isinstance(body["config"], dict):
                raise HTTPException(422, "invalid target config")
            merged = TargetBody(
                kind=body.get("kind", old["kind"]),
                name=body.get("name", old["name"]),
                config={**oldconfig, **body.get("config", {})},
            )
            if native_tasks and (
                any(
                    task["execution_id"] is not None
                    or task["state"] not in ("queued", "sync_pending")
                    or (task["state"] == "queued" and task["phase"] not in (
                        "native_recovery", "native_recovery_failed", "native_cancel_pending"
                    ))
                    for task in native_tasks
                )
                or merged.kind != old["kind"]
                or any(
                    merged.config.get(field) != oldconfig.get(field)
                    for field in set(merged.config) | set(oldconfig)
                    if field != "management_key"
                )
            ):
                raise Conflict("native authorization is bound to this target; only idle administrator-key or name repair is allowed")
            pending = conn.execute(
                "SELECT id FROM tasks WHERE target_id=? AND state='sync_pending'",
                (target_id,),
            ).fetchall()
            if pending and (
                merged.kind != old["kind"]
                or any(
                    merged.config.get(k) != oldconfig.get(k)
                    for k in ("base_url", "allow_http", "compatibility")
                )
            ):
                raise Conflict(
                    "pending credentials are bound to this target endpoint and compatibility"
                )
            conn.execute(
                "UPDATE targets SET kind=?,name=?,config_cipher=?,version=version+1,verification=? WHERE id=?",
                (
                    merged.kind,
                    merged.name,
                    encrypt(json.dumps(merged.config), app.state.key),
                    "unverified",
                    target_id,
                ),
            )
            rebound_ids = {task["id"] for task in pending} | {task["id"] for task in native_tasks}
            for task_id in rebound_ids:
                conn.execute(
                    "UPDATE tasks SET target_version=? WHERE id=?",
                    (old["version"] + 1, task_id),
                )
                event(conn, task_id)
            return public_target(get_row(conn, "targets", target_id), app.state.key)

    @app.delete("/api/v1/targets/{target_id}")
    def delete_target(target_id: int):
        with database(settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            get_row(conn, "targets", target_id)
            check_busy(conn, "target_id", target_id, True)
            conn.execute("DELETE FROM tasks WHERE target_id=?", (target_id,))
            conn.execute("DELETE FROM targets WHERE id=?", (target_id,))
        return {"deleted": True}

    @app.post("/api/v1/targets/{target_id}/test")
    def test_target(target_id: int):
        from .integrations import test_connection

        with database(settings.db_path) as conn:
            t = dict(get_row(conn, "targets", target_id))
            t["config"] = json.loads(decrypt(t["config_cipher"], app.state.key))
        try:
            return test_connection(t)
        except Exception:
            raise HTTPException(
                502, "target connection or compatibility check failed"
            ) from None

    @app.post("/api/v1/accounts/{account_id}/tasks")
    def create_task(account_id: int, body: TaskBody):
        return app.state.queue.create(account_id, body.target_id, body.idempotency_key)

    @app.post("/api/v1/accounts/{account_id}/login-flow")
    def login_flow(account_id: int, body: LoginFlowBody):
        return {"tasks": app.state.queue.create_login_flow(account_id, body.voice_target_id, body.cli_target_id, body.idempotency_key)}

    @app.post("/api/v1/accounts/{account_id}/browser")
    def account_browser(account_id: int, body: BrowserBody | None = None):
        return {"task": app.state.queue.open_browser(account_id, body.idempotency_key if body else None)}

    @app.get("/api/v1/tasks")
    def tasks():
        with database(settings.db_path) as conn:
            return {
                "tasks": [
                    public_task(r)
                    for r in conn.execute(
                        "SELECT * FROM tasks ORDER BY id DESC LIMIT 500"
                    )
                ]
            }

    @app.get("/api/v1/tasks/{task_id}")
    def task(task_id: int):
        with database(settings.db_path) as conn:
            row = get_row(conn, "tasks", task_id)
            return {
                **public_task(row),
                "account_username": get_row(conn, "accounts", row["account_id"])[
                    "username"
                ],
            }

    @app.post("/api/v1/tasks/{task_id}/discard-sync")
    def discard_sync(task_id: int, body: DiscardBody):
        return app.state.queue.action(
            task_id, "discard-sync", confirmation=body.confirmation
        )

    @app.post("/api/v1/tasks/{task_id}/code")
    def submit_code(task_id: int, body: CodeBody):
        return app.state.queue.action(task_id, "code", body.code, body.submission_id)

    for action in ("cancel", "takeover", "continue", "retry-sync"):

        def make_action(name):
            def endpoint(task_id: int):
                return app.state.queue.action(task_id, name)

            return endpoint

        app.add_api_route(
            "/api/v1/tasks/{task_id}/" + action, make_action(action), methods=["POST"]
        )

    @app.get("/api/v1/tasks/{task_id}/history")
    def task_history(task_id: int):
        with database(settings.db_path) as conn:
            get_row(conn, "tasks", task_id)
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        return {
            "events": [
                {
                    **{
                        k: r[k]
                        for k in (
                            "state",
                            "phase",
                            "message",
                            "takeover_available",
                            "created_at",
                        )
                    },
                    "id": r["task_id"],
                    "event_id": r["id"],
                }
                for r in rows
            ]
        }

    @app.get("/api/v1/tasks/{task_id}/events")
    async def task_events(task_id: int, request: Request):
        with database(settings.db_path) as conn:
            get_row(conn, "tasks", task_id)
        try:
            cursor = int(
                request.headers.get(
                    "last-event-id", request.query_params.get("after", "0")
                )
            )
        except ValueError:
            raise HTTPException(422, "invalid event cursor") from None

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                if not session(request.cookies.get("bridge_session")):
                    break
                with database(settings.db_path) as conn:
                    rows = conn.execute(
                        "SELECT * FROM task_events WHERE task_id=? AND id>? ORDER BY id LIMIT 100",
                        (task_id, cursor),
                    ).fetchall()
                    current = conn.execute(
                        "SELECT state FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()
                for row in rows:
                    cursor = row["id"]
                    data = {
                        k: row[k]
                        for k in (
                            "state",
                            "phase",
                            "message",
                            "takeover_available",
                            "created_at",
                        )
                    }
                    data.update(id=row["task_id"], event_id=row["id"])
                    yield f"id: {cursor}\nevent: task\ndata: {json.dumps(data)}\n\n"
                if not current or (
                    current[0] in ("succeeded", "failed", "cancelled", "interrupted")
                    and len(rows) < 100
                ):
                    break
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    @app.websocket("/api/v1/tasks/{task_id}/monitor")
    async def monitor(ws: WebSocket, task_id: int):
        await account_window(ws, task_id, read_only=True)

    @app.websocket("/api/v1/tasks/{task_id}/takeover")
    async def takeover(ws: WebSocket, task_id: int):
        await account_window(ws, task_id, read_only=False)

    async def account_window(ws: WebSocket, task_id: int, *, read_only: bool):
        from .rfb_monitor import ReadOnlyRFB

        cookie = ws.cookies.get("bridge_session")
        if (
            not session(cookie)
            or not ws.headers.get("origin")
            or not same_origin(ws.headers)
        ):
            await ws.close(code=1008)
            return

        states = ("running", "waiting_human") if read_only else ("waiting_human",)
        owner = None

        def valid():
            nonlocal owner
            if not session(cookie):
                return False
            with database(settings.db_path) as conn:
                row = conn.execute(
                    "SELECT account_id,execution_id,state FROM tasks WHERE id=? "
                    "AND execution_id IS NOT NULL AND takeover_available=1 "
                    "AND lease_until>? AND cancel_requested=0",
                    (task_id, time.time()),
                ).fetchone()
                if not row or row["state"] not in states:
                    return False
                identity = (row["account_id"], row["execution_id"])
                if owner is None:
                    owner = identity
                return identity == owner

        if not valid():
            await ws.close(code=1008)
            return
        import websockets

        reader = ReadOnlyRFB() if read_only else None
        await ws.accept()
        try:
            async with websockets.connect(
                settings.takeover_url, max_size=4 * 1024 * 1024, open_timeout=5
            ) as remote:

                async def to_remote():
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            return
                        if not valid():
                            return
                        data = msg.get("bytes")
                        if reader is not None:
                            # Forward only complete, validated RFB client messages.
                            for frame in reader.feed(data):
                                if not valid():
                                    return
                                await remote.send(frame)
                        else:
                            await remote.send(data if data is not None else msg.get("text", ""))

                async def to_client():
                    async for msg in remote:
                        if not valid():
                            return
                        if isinstance(msg, bytes):
                            await ws.send_bytes(msg)
                        elif reader is None:
                            await ws.send_text(msg)
                        else:
                            return

                async def revocation():
                    while valid():
                        await asyncio.sleep(0.5)

                jobs = [
                    asyncio.create_task(f()) for f in (to_remote, to_client, revocation)
                ]
                try:
                    await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for job in jobs:
                        job.cancel()
                    await asyncio.gather(*jobs, return_exceptions=True)
        except (Exception, WebSocketDisconnect):
            pass
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    @app.get("/api/v1/runtime")
    def runtime():
        with database(settings.db_path) as conn:
            worker = conn.execute(
                "SELECT * FROM runtime ORDER BY heartbeat DESC LIMIT 1"
            ).fetchone()
            config = conn.execute("SELECT * FROM settings").fetchone()
        alive = bool(worker and worker["heartbeat"] > time.time() - 45)
        return {
            "worker_alive": alive,
            "browser_available": bool(alive and worker["browser_available"]),
            "maintenance_enabled": bool(config["maintenance_enabled"]),
            "version": "0.2.0",
        }

    @app.get("/api/v1/settings")
    def get_settings():
        with database(settings.db_path) as conn:
            return dict(
                conn.execute(
                    "SELECT maintenance_enabled,retention_days FROM settings"
                ).fetchone()
            )

    @app.patch("/api/v1/settings")
    def patch_settings(body: SettingsBody):
        values = body.model_dump(exclude_none=True)
        if values:
            with database(settings.db_path) as conn:
                conn.execute(
                    "UPDATE settings SET " + ",".join(f"{k}=?" for k in values),
                    tuple(values.values()),
                )
        return get_settings()

    novnc = Path("/usr/share/novnc")
    if novnc.exists():
        app.mount("/novnc", StaticFiles(directory=novnc), name="novnc")
    if settings.static_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=settings.static_dir / "assets", check_dir=False),
            name="assets",
        )

        @app.get("/{path:path}")
        def index(path: str):
            if path.startswith(("api/", "novnc/")):
                raise HTTPException(404, "not found")
            return FileResponse(settings.static_dir / "index.html")

    return app


app = create_app()
