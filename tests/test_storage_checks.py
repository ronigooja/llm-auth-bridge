from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from app.storage import StorageCheck, check_storage


def mountinfo(mountpoint, filesystem, mount_id=42):
    return f"{mount_id} 1 0:1 / {mountpoint} rw,relatime - {filesystem} synthetic rw\n"


def test_storage_check_warns_for_network_filesystem(tmp_path):
    database = tmp_path / "data" / "bridge.db"
    lock = tmp_path / "data" / "browser.lock"
    database.parent.mkdir()
    mountinfo_path = tmp_path / "mountinfo"
    mountinfo_path.write_text(mountinfo(database.parent, "nfs4"))
    settings = Settings(db_path=database, lock_file=lock, storage_check="warn")

    result = check_storage(settings, mountinfo_path)

    assert result.warnings == (
        "database path is on unsupported network filesystem nfs4",
        "browser lock path is on unsupported network filesystem nfs4",
    )


def test_storage_check_warns_for_different_volumes(tmp_path):
    database = tmp_path / "data" / "bridge.db"
    lock = tmp_path / "lock" / "browser.lock"
    database.parent.mkdir()
    lock.parent.mkdir()
    mountinfo_path = tmp_path / "mountinfo"
    mountinfo_path.write_text(
        mountinfo(database.parent, "ext4", 42) + mountinfo(lock.parent, "xfs", 43)
    )
    settings = Settings(db_path=database, lock_file=lock, storage_check="warn")

    result = check_storage(settings, mountinfo_path)

    assert result.warnings == (
        "database and browser lock are on different filesystem volumes",
    )


def test_storage_check_can_be_disabled(tmp_path):
    database = tmp_path / "data" / "bridge.db"
    database.parent.mkdir()
    mountinfo_path = tmp_path / "mountinfo"
    mountinfo_path.write_text(mountinfo(database.parent, "nfs"))
    settings = Settings(
        db_path=database,
        lock_file=database.parent / "lock",
        storage_check="off",
    )

    assert not check_storage(settings, mountinfo_path).warnings


def test_create_app_does_not_run_storage_check(monkeypatch, settings):
    monkeypatch.setattr(
        "app.main.check_storage",
        lambda settings: (_ for _ in ()).throw(AssertionError()),
    )

    create_app(replace(settings, storage_check="off"))


def test_readyz_reports_storage_warning(settings, monkeypatch):
    warning = "database path is on unsupported network filesystem nfs"
    monkeypatch.setattr(
        "app.main.check_storage", lambda settings: StorageCheck((warning,))
    )

    with TestClient(create_app(replace(settings, storage_check="warn"))) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "storage": {"status": "warning", "warnings": [warning]},
    }


def test_readyz_can_fail_for_storage_warning(settings, monkeypatch):
    warning = "database and browser lock are on different filesystem volumes"
    monkeypatch.setattr(
        "app.main.check_storage", lambda settings: StorageCheck((warning,))
    )

    with TestClient(create_app(replace(settings, storage_check="fail"))) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "reason": "unsupported storage/lock setup",
        "warnings": [warning],
    }
