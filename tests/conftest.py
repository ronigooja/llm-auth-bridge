import pytest
from app.cli import initialize
from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    value = Settings(
        db_path=tmp_path / "data" / "bridge.db",
        key_file=tmp_path / "secret" / "key",
        secure_cookie=False,
    )
    initialize(value, "synthetic-password-123")
    return value


@pytest.fixture
def client(settings):
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as c:
        yield c


def login(client):
    response = client.post(
        "/api/v1/auth/login", json={"password": "synthetic-password-123"}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture
def admin(client):
    return login(client)


@pytest.fixture
def resources(admin):
    target = admin.post(
        "/api/v1/targets",
        json={
            "kind": "cliproxyapi",
            "name": "Test CPA",
            "config": {
                "base_url": "https://cpa.example",
                "management_key": "synthetic-secret",
            },
        },
    )
    assert target.status_code == 200, target.text
    account = admin.post(
        "/api/v1/accounts",
        json={
            "username": "test@example.com",
            "password": "synthetic-password",
            "totp": "JBSWY3DPEHPK3PXP",
            "route_type": "direct",
            "target_ids": [target.json()["id"]],
        },
    )
    assert account.status_code == 200, account.text
    return account.json()["id"], target.json()["id"]
