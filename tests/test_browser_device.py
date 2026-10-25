"""Synthetic profile fixtures only: no browser or real account state."""

import io
from pathlib import Path
import tarfile

import pytest

from app import browser_device
from app.browser_device import DeviceArchiveError, device_directory


class Control:
    def __init__(self, archive=None):
        self.archive = archive
        self.saves = 0
        self.fail_save = False

    def load_device(self):
        return self.archive

    def save_device(self, archive):
        if self.fail_save:
            raise RuntimeError("synthetic lease expired")
        self.archive = archive
        self.saves += 1


def packed(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                member.linkname = content.decode()
                archive.addfile(member)
    return buffer.getvalue()


def test_roundtrip_keeps_full_profile_and_excludes_transient_data():
    control = Control()
    retained = [
        "Local State", "Default/Network/Cookies", "Default/IndexedDB/example/data",
        "Default/Local Storage/leveldb/data", "Default/Session Storage/data",
        "Default/Preferences", "Default/Extensions/synthetic/manifest.json",
    ]
    with device_directory({"id": "synthetic-a"}, control) as device:
        first_path = device.path
        assert not device.restored
        assert first_path.stat().st_mode & 0o777 == 0o700
        for name in retained:
            target = device.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic-profile-data")
        cache = device.path / "Default/Cache/data"
        cache.parent.mkdir()
        cache.write_bytes(b"synthetic-cache")
        (device.path / "DevToolsActivePort").write_text("synthetic")
        (device.path / "SingletonLock").symlink_to("/synthetic/nonexistent")
    assert not first_path.exists()
    assert control.saves == 1
    with device_directory({"id": "synthetic-a"}, control) as device:
        assert device.restored
        assert device.path != first_path
        for name in retained:
            target = device.path / name
            assert target.read_bytes() == b"synthetic-profile-data"
            assert target.stat().st_mode & 0o777 == 0o600
        assert not (device.path / "Default/Cache").exists()
        assert not (device.path / "DevToolsActivePort").exists()
        assert not (device.path / "SingletonLock").is_symlink()
    assert not device.path.exists()


def test_controls_isolate_accounts_and_account_paths_are_ignored(tmp_path):
    first, second = Control(), Control()
    # Untrusted account fields must never select the plaintext directory.
    account = {"id": "../synthetic-a", "device_path": str(tmp_path)}
    with device_directory(account, first) as device:
        (device.path / "Local State").write_text("synthetic-first")
    with device_directory(account, second) as device:
        assert not device.restored
        assert not (device.path / "Local State").exists()
        (device.path / "Local State").write_text("synthetic-second")
    with device_directory(account, first) as device:
        assert (device.path / "Local State").read_text() == "synthetic-first"
    assert list(tmp_path.iterdir()) == []


def test_error_snapshots_partial_profile_and_removes_plaintext():
    control = Control()
    original = RuntimeError("synthetic browser failure")
    with pytest.raises(RuntimeError) as caught:
        with device_directory({}, control) as device:
            (device.path / "Local State").write_text("synthetic-progress")
            raise original
    assert caught.value is original
    assert not device.path.exists()
    assert control.saves == 1
    with device_directory({}, control) as device:
        assert (device.path / "Local State").read_text() == "synthetic-progress"


def test_save_failure_preserves_cancellation_and_cleanup():
    control = Control()
    control.fail_save = True
    original = KeyboardInterrupt("synthetic cancellation")
    with pytest.raises(KeyboardInterrupt) as caught:
        with device_directory({}, control) as device:
            raise original
    assert caught.value is original
    assert not device.path.exists()


def test_normal_save_failure_is_visible_and_plaintext_removed():
    control = Control()
    control.fail_save = True
    with pytest.raises(RuntimeError, match="lease expired"):
        with device_directory({}, control) as device:
            (device.path / "Local State").write_text("synthetic")
    assert not device.path.exists()


@pytest.mark.parametrize("name", ["../escape", "/escape", "a/../../escape", "a/./b", "a//b", "a\\b"])
def test_rejects_unsafe_paths(name):
    control = Control(packed([(name, tarfile.REGTYPE, b"synthetic")]))
    with pytest.raises(DeviceArchiveError, match="path"):
        with device_directory({}, control):
            pytest.fail("Unsafe archive yielded a directory")
    assert control.saves == 0


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_rejects_non_regular_members(kind):
    control = Control(packed([("synthetic-link", kind, b"../outside")]))
    with pytest.raises(DeviceArchiveError, match="Unsupported"):
        with device_directory({}, control):
            pytest.fail("Unsafe archive yielded a directory")


def test_rejects_duplicate_members():
    control = Control(packed([
        ("Local State", tarfile.REGTYPE, b"first"),
        ("Local State", tarfile.REGTYPE, b"second"),
    ]))
    with pytest.raises(DeviceArchiveError, match="Duplicate"):
        with device_directory({}, control):
            pytest.fail("Duplicate archive yielded a directory")


def test_restore_failure_removes_temporary_directory(monkeypatch, tmp_path):
    original = browser_device.tempfile.TemporaryDirectory
    paths = []

    def tracked_directory(**kwargs):
        kwargs["dir"] = str(tmp_path)
        directory = original(**kwargs)
        paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(browser_device.tempfile, "TemporaryDirectory", tracked_directory)
    with pytest.raises(DeviceArchiveError):
        with device_directory({}, Control(b"synthetic-invalid-gzip")):
            pytest.fail("Malformed archive yielded a directory")
    assert paths and all(not path.exists() for path in paths)


def test_archive_size_limits(monkeypatch):
    archive = packed([("Local State", tarfile.REGTYPE, b"synthetic" * 100)])
    monkeypatch.setattr(browser_device, "MAX_COMPRESSED_BYTES", len(archive) - 1)
    with pytest.raises(DeviceArchiveError, match="compressed size"):
        with device_directory({}, Control(archive)):
            pytest.fail("Oversized archive yielded a directory")
    monkeypatch.setattr(browser_device, "MAX_COMPRESSED_BYTES", len(archive) + 1)
    monkeypatch.setattr(browser_device, "MAX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(DeviceArchiveError, match="uncompressed size"):
        with device_directory({}, Control(archive)):
            pytest.fail("Expansion limit archive yielded a directory")


def test_member_limit_and_snapshot_limit(monkeypatch):
    archive = packed([
        ("first", tarfile.REGTYPE, b"synthetic"),
        ("second", tarfile.REGTYPE, b"synthetic"),
    ])
    monkeypatch.setattr(browser_device, "MAX_MEMBERS", 1)
    with pytest.raises(DeviceArchiveError, match="member limit"):
        with device_directory({}, Control(archive)):
            pytest.fail("Too many members yielded a directory")
    control = Control()
    with pytest.raises(DeviceArchiveError, match="member limit"):
        with device_directory({}, control) as device:
            (device.path / "first").touch()
            (device.path / "second").touch()
    assert not device.path.exists()
    assert control.saves == 0


def test_snapshot_rejects_non_transient_symlink():
    control = Control()
    with pytest.raises(DeviceArchiveError, match="Unsupported"):
        with device_directory({}, control) as device:
            (device.path / "synthetic-link").symlink_to("/synthetic/target")
    assert not device.path.exists()
    assert control.saves == 0


@pytest.mark.parametrize("limit", ["MAX_COMPRESSED_BYTES", "MAX_UNCOMPRESSED_BYTES"])
def test_snapshot_size_limit_cleans_up_without_saving(monkeypatch, limit):
    monkeypatch.setattr(browser_device, limit, 32)
    control = Control()
    with pytest.raises(DeviceArchiveError, match="size limit"):
        with device_directory({}, control) as device:
            (device.path / "Local State").write_bytes(b"synthetic" * 100)
    assert not device.path.exists()
    assert control.saves == 0


def test_truncated_gzip_archive_is_rejected():
    archive = packed([("Local State", tarfile.REGTYPE, b"synthetic")])
    with pytest.raises(DeviceArchiveError):
        with device_directory({}, Control(archive[:-8])):
            pytest.fail("Truncated archive yielded a directory")
