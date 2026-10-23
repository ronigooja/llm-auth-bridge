import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, AnyHttpUrl
from .config import MASTER_KEY_FILE
from .crypto import load_key, encrypt
from .db import connect
from .importer import parse_line, preview

app = FastAPI(title="LLM Auth Bridge", version="0.1.0")
KEY = load_key(MASTER_KEY_FILE)

class ImportBody(BaseModel): text: str
class AccountBody(BaseModel): username: str; password: str; totp: str; mailbox_url: AnyHttpUrl | None = None
class TargetBody(BaseModel): kind: str; name: str; config: dict

def public_account(row):
    return {"id": row["id"], "username": row["username"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

@app.get("/healthz")
def health(): return {"status": "ok"}

@app.post("/api/v1/import/preview")
def import_preview(body: ImportBody): return {"records": preview(body.text)}

@app.post("/api/v1/import/confirm")
def import_confirm(body: ImportBody):
    conn = connect(); imported = []
    try:
        for line in body.text.splitlines():
            if not line.strip(): continue
            record = parse_line(line)
            conn.execute("INSERT INTO accounts(username,password_cipher,totp_cipher,mailbox_url_cipher) VALUES(?,?,?,?)", (record.username, encrypt(record.password, KEY), encrypt(record.totp, KEY), encrypt(record.mailbox_url, KEY) if record.mailbox_url else None))
            imported.append(record.username)
        conn.commit()
    except ValueError as exc:
        conn.rollback(); raise HTTPException(422, str(exc))
    except Exception as exc:
        conn.rollback(); raise HTTPException(409, "account already exists or import failed") from exc
    finally: conn.close()
    return {"imported": imported}

@app.get("/api/v1/accounts")
def accounts():
    conn = connect(); rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall(); conn.close()
    return {"accounts": [public_account(r) for r in rows]}

@app.post("/api/v1/accounts")
def create_account(body: AccountBody):
    conn = connect()
    try:
        cur = conn.execute("INSERT INTO accounts(username,password_cipher,totp_cipher,mailbox_url_cipher) VALUES(?,?,?,?)", (body.username, encrypt(body.password, KEY), encrypt(body.totp, KEY), encrypt(str(body.mailbox_url), KEY) if body.mailbox_url else None)); conn.commit(); row = conn.execute("SELECT * FROM accounts WHERE id=?", (cur.lastrowid,)).fetchone(); return public_account(row)
    except Exception as exc: conn.rollback(); raise HTTPException(409, "account already exists") from exc
    finally: conn.close()

@app.get("/api/v1/targets")
def targets():
    conn = connect(); rows = conn.execute("SELECT id,kind,name,created_at FROM targets ORDER BY id").fetchall(); conn.close(); return {"targets": [dict(r) for r in rows]}

@app.post("/api/v1/targets")
def create_target(body: TargetBody):
    if body.kind not in ("cliproxyapi", "chatgpt-web-voice"): raise HTTPException(422, "unsupported target kind")
    conn = connect(); cur = conn.execute("INSERT INTO targets(kind,name,config_cipher) VALUES(?,?,?)", (body.kind, body.name, encrypt(json.dumps(body.config), KEY))); conn.commit(); row = conn.execute("SELECT id,kind,name,created_at FROM targets WHERE id=?", (cur.lastrowid,)).fetchone(); conn.close(); return dict(row)

@app.post("/api/v1/accounts/{account_id}/tasks")
def create_task(account_id: int, target_id: int | None = None):
    conn = connect()
    if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone(): conn.close(); raise HTTPException(404, "account not found")
    cur = conn.execute("INSERT INTO tasks(account_id,target_id,kind,state,phase,message) VALUES(?,?,?,?,?,?)", (account_id,target_id,"login","queued","queued","Waiting for worker")); conn.commit(); row = conn.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone(); conn.close(); return {"id": row["id"], "state": row["state"], "phase": row["phase"]}

@app.get("/api/v1/tasks/{task_id}")
def task(task_id: int):
    conn = connect(); row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone(); conn.close()
    if not row: raise HTTPException(404, "task not found")
    return {k: row[k] for k in ("id","account_id","target_id","kind","state","phase","message","created_at","updated_at")}

