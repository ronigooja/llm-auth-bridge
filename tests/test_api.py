import json
import pytest
from app.db import database
from app.crypto import load_key, decrypt
from app.queue import Queue


@pytest.mark.parametrize(
    "path",
    [
        "accounts",
        "targets",
        "tasks",
        "settings",
        "runtime",
        "tasks/1/events",
        "auth/session",
    ],
)
def test_business_api_requires_auth(client, path):
    assert client.get("/api/v1/" + path).status_code == 401


def test_csrf_logout_and_password_revocation(admin, settings):
    csrf = admin.headers.pop("X-CSRF-Token")
    assert admin.post("/api/v1/accounts", json={}).status_code == 403
    admin.headers["X-CSRF-Token"] = csrf
    assert (
        admin.post(
            "/api/v1/auth/password",
            json={
                "current_password": "synthetic-password-123",
                "new_password": "changed-synthetic-password",
            },
        ).status_code
        == 200
    )
    assert admin.get("/api/v1/accounts").status_code == 401


def test_login_rate_limited(client):
    for _ in range(5):
        assert (
            client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code
            == 401
        )
    r = client.post("/api/v1/auth/login", json={"password": "synthetic-password-123"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_cross_origin_login_and_mutation(client, admin):
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"password": "synthetic-password-123"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/v1/auth/logout", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_cookie_and_logout(admin):
    r = admin.post("/api/v1/auth/login", json={"password": "synthetic-password-123"})
    assert (
        "HttpOnly" in r.headers["set-cookie"]
        and "SameSite=strict" in r.headers["set-cookie"]
    )
    admin.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert admin.post("/api/v1/auth/logout").status_code == 200
    assert admin.get("/api/v1/accounts").status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "u", "password": "PASSWORD-SECRET", "totp": "INVALID-SEED-SECRET"},
        {
            "username": "u",
            "password": "PASSWORD-SECRET",
            "proxy": {"server": "http://name:PROXY-SECRET@host:80"},
        },
        {
            "username": "u",
            "password": "PASSWORD-SECRET",
            "mailbox_url": "file:///MAILBOX-SECRET",
        },
        {
            "username": "u",
            "password": "PASSWORD-SECRET",
            "mailbox_url": "https://127.0.0.1/MAILBOX-SECRET",
        },
        {"username": "u", "password": "********"},
    ],
)
def test_sensitive_validation_never_echoes(admin, payload):
    r = admin.post("/api/v1/accounts", json=payload)
    assert r.status_code == 422
    for secret in (
        "PASSWORD-SECRET",
        "INVALID-SEED-SECRET",
        "PROXY-SECRET",
        "MAILBOX-SECRET",
        "********",
    ):
        assert secret not in r.text


def test_public_account_hides_all_secrets(admin, settings):
    body = {
        "username": "u",
        "password": "private-password",
        "totp": "JBSWY3DPEHPK3PXP",
        "mailbox_url": "https://mail.example/private-inbox",
        "route_type": "proxy",
        "proxy": {
            "server": "socks5://proxy.example:1080",
            "username": "proxy-user",
            "password": "proxy-secret",
        },
    }
    r = admin.post("/api/v1/accounts", json=body)
    assert r.status_code == 200, r.text
    for secret in (
        "private-password",
        "JBSWY3DPEHPK3PXP",
        "private-inbox",
        "proxy-secret",
        "proxy-user",
    ):
        assert secret not in r.text
    with database(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM accounts").fetchone()
        assert "proxy-secret" not in str(dict(row))
        assert (
            decrypt(row["password_cipher"], load_key(settings.key_file))
            == "private-password"
        )
    id = r.json()["id"]
    assert (
        admin.patch(f"/api/v1/accounts/{id}", json={"totp": None}).json()["has_totp"]
        is False
    )
    assert (
        admin.patch(f"/api/v1/accounts/{id}", json={"username": "new"}).json()[
            "has_password"
        ]
        is True
    )


def test_import_preview_database_duplicate_and_atomic_confirm(admin):
    text = "a----p----JBSWY3DPEHPK3PXP\nA----p----JBSWY3DPEHPK3PXP"
    records = admin.post("/api/v1/import/preview", json={"text": text}).json()[
        "records"
    ]
    assert not records[1]["valid"]
    assert admin.post("/api/v1/import/confirm", json={"text": text}).status_code == 422
    assert admin.get("/api/v1/accounts").json()["accounts"] == []
    valid = "a----p----JBSWY3DPEHPK3PXP"
    assert admin.post("/api/v1/import/confirm", json={"text": valid}).status_code == 200
    assert not admin.post("/api/v1/import/preview", json={"text": valid}).json()[
        "records"
    ][0]["valid"]
    assert (
        admin.post(
            "/api/v1/import/confirm",
            json={"text": valid + "\nb----p----JBSWY3DPEHPK3PXP"},
        ).status_code
        == 422
    )
    assert len(admin.get("/api/v1/accounts").json()["accounts"]) == 1


def test_target_patch_preserves_secret(admin, settings, resources):
    _, id = resources
    r = admin.patch(
        f"/api/v1/targets/{id}", json={"config": {"base_url": "https://new.example"}}
    )
    assert r.status_code == 200, r.text
    assert "synthetic-secret" not in r.text
    with database(settings.db_path) as conn:
        row = conn.execute(
            "SELECT config_cipher FROM targets WHERE id=?", (id,)
        ).fetchone()
        assert (
            json.loads(decrypt(row[0], load_key(settings.key_file)))["management_key"]
            == "synthetic-secret"
        )


def test_task_creation_requires_target_and_route_and_binding(admin, resources):
    a, t = resources
    assert admin.post(f"/api/v1/accounts/{a}/tasks").status_code == 422
    assert (
        admin.patch(f"/api/v1/accounts/{a}", json={"route_type": "unset"}).status_code
        == 200
    )
    assert (
        admin.post(f"/api/v1/accounts/{a}/tasks", json={"target_id": t}).status_code
        == 409
    )
    admin.patch(
        f"/api/v1/accounts/{a}", json={"route_type": "direct", "target_ids": []}
    )
    assert (
        admin.post(f"/api/v1/accounts/{a}/tasks", json={"target_id": t}).status_code
        == 409
    )


def test_idempotency_conflict_and_active_delete(admin, resources):
    a, t = resources
    body = {"target_id": t, "idempotency_key": "test-request-id"}
    first = admin.post(f"/api/v1/accounts/{a}/tasks", json=body)
    assert first.status_code == 200, first.text
    assert (
        admin.post(f"/api/v1/accounts/{a}/tasks", json=body).json()["id"]
        == first.json()["id"]
    )
    assert (
        admin.post(f"/api/v1/accounts/{a}/tasks", json={"target_id": t}).status_code
        == 409
    )
    assert admin.delete(f"/api/v1/accounts/{a}").status_code == 409
    assert admin.delete(f"/api/v1/targets/{t}").status_code == 409
    assert (
        admin.post(f"/api/v1/tasks/{first.json()['id']}/cancel").json()["state"]
        == "cancelled"
    )
    assert admin.delete(f"/api/v1/accounts/{a}").status_code == 200


def test_sse_reconnect_terminal_event(admin, resources):
    a, t = resources
    id = admin.post(f"/api/v1/accounts/{a}/tasks", json={"target_id": t}).json()["id"]
    admin.post(f"/api/v1/tasks/{id}/cancel")
    response = admin.get(f"/api/v1/tasks/{id}/events")
    assert response.status_code == 200 and '"state": "cancelled"' in response.text
    first_id = response.text.split("id: ")[1].split("\n")[0]
    resumed = admin.get(
        f"/api/v1/tasks/{id}/events", headers={"Last-Event-ID": first_id}
    )
    assert (
        '"state": "queued"' not in resumed.text
        and '"state": "cancelled"' in resumed.text
    )


def test_websocket_requires_auth_and_origin(client, admin, resources):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/tasks/1/takeover"):
            pass
    a, t = resources
    id = admin.post(f"/api/v1/accounts/{a}/tasks", json={"target_id": t}).json()["id"]
    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect(
            f"/api/v1/tasks/{id}/takeover", headers={"Origin": "http://evil.example"}
        ):
            pass


def test_proxy_patch_preserves_omitted_password(admin, settings):
    r = admin.post(
        "/api/v1/accounts",
        json={
            "username": "proxy-user",
            "password": "synthetic",
            "route_type": "proxy",
            "proxy": {
                "server": "http://proxy.example:8000",
                "username": "name",
                "password": "proxy-synthetic-secret",
            },
        },
    )
    id = r.json()["id"]
    assert (
        admin.patch(
            f"/api/v1/accounts/{id}",
            json={"proxy": {"server": "http://newproxy.example:8000"}},
        ).status_code
        == 200
    )
    with database(settings.db_path) as conn:
        proxy = json.loads(
            decrypt(
                conn.execute(
                    "SELECT proxy_cipher FROM accounts WHERE id=?", (id,)
                ).fetchone()[0],
                load_key(settings.key_file),
            )
        )
        assert proxy["password"] == "proxy-synthetic-secret"


def test_masked_target_secret_rejected(admin, resources):
    _, t = resources
    assert (
        admin.patch(
            f"/api/v1/targets/{t}", json={"config": {"management_key": "********"}}
        ).status_code
        == 422
    )


def test_password_change_fences_concurrent_old_password_login(
    admin, settings, monkeypatch
):
    import threading
    from fastapi.testclient import TestClient
    from app import main

    entered = threading.Event()
    release = threading.Event()
    results = []
    original = main.HASHER.verify

    def verify(hash_value, password):
        result = original(hash_value, password)
        if (
            password == "synthetic-password-123"
            and threading.current_thread().name.startswith("AnyIO")
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(
        type(main.HASHER),
        "verify",
        lambda self, hash_value, password: verify(hash_value, password),
    )

    def competing_login():
        with TestClient(main.create_app(settings)) as other:
            results.append(
                other.post(
                    "/api/v1/auth/login", json={"password": "synthetic-password-123"}
                ).status_code
            )

    thread = threading.Thread(target=competing_login)
    thread.start()
    assert entered.wait(3)
    try:
        assert (
            admin.post(
                "/api/v1/auth/password",
                json={
                    "current_password": "synthetic-password-123",
                    "new_password": "new-synthetic-password",
                },
            ).status_code
            == 200
        )
    finally:
        release.set()
        thread.join(5)
    assert results == [401]


def test_concurrent_case_insensitive_imports_are_atomic(admin, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app import main

    barrier = threading.Barrier(2)
    original = main.preview

    def preview(text):
        result = original(text)
        barrier.wait(timeout=3)
        return result

    monkeypatch.setattr(main, "preview", preview)

    def confirm(username):
        return admin.post(
            "/api/v1/import/confirm",
            json={"text": username + "----synthetic----JBSWY3DPEHPK3PXP"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(confirm, ["Case@example.com", "case@example.com"]))
    assert sorted(codes) == [200, 409]
    assert len(admin.get("/api/v1/accounts").json()["accounts"]) == 1
