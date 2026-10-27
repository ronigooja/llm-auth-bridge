"""Synthetic profile fixtures only: no browser or real account state."""

import io
import json
import os
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


def packed(entries, *, marked=True):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if marked:
            payload = json.dumps(browser_device.ARCHIVE_FORMAT).encode()
            marker = tarfile.TarInfo(browser_device.ARCHIVE_FORMAT_FILE)
            marker.size = len(payload)
            archive.addfile(marker, io.BytesIO(payload))
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
        "cookies.sqlite", "cookies.sqlite-wal", "prefs.js", "storage.sqlite",
        "storage/default/https+++synthetic.example/ls/data.sqlite",
        "storage/default/https+++synthetic.example/idb/data.sqlite",
        "sessionstore-backups/recovery.jsonlz4", "extensions/synthetic/manifest.json",
    ]
    with device_directory({"id": "synthetic-a"}, control) as device:
        device.mark_ready()
        first_path = device.path
        assert not device.restored
        assert first_path.stat().st_mode & 0o777 == 0o700
        for name in retained:
            target = device.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic-profile-data")
        cache = device.path / "cache2/entries/data"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"synthetic-cache")
        (device.path / ".parentlock").touch()
        (device.path / "parent.lock").touch()
        (device.path / "lock").symlink_to("synthetic-host:+12345")
    assert not first_path.exists()
    assert control.saves == 1
    with device_directory({"id": "synthetic-a"}, control) as device:
        device.mark_ready()
        assert device.restored
        assert device.path != first_path
        for name in retained:
            target = device.path / name
            assert target.read_bytes() == b"synthetic-profile-data"
            assert target.stat().st_mode & 0o777 == 0o600
        assert not (device.path / "cache2").exists()
        assert not (device.path / ".parentlock").exists()
        assert not (device.path / "parent.lock").exists()
        assert not (device.path / "lock").is_symlink()
        assert not (device.path / browser_device.ARCHIVE_FORMAT_FILE).exists()
    assert not device.path.exists()


def test_controls_isolate_accounts_and_account_paths_are_ignored(tmp_path):
    first, second = Control(), Control()
    # Untrusted account fields must never select the plaintext directory.
    account = {"id": "../synthetic-a", "device_path": str(tmp_path)}
    with device_directory(account, first) as device:
        device.mark_ready()
        (device.path / "prefs.js").write_text("synthetic-first")
    with device_directory(account, second) as device:
        device.mark_ready()
        assert not device.restored
        assert not (device.path / "prefs.js").exists()
        (device.path / "prefs.js").write_text("synthetic-second")
    with device_directory(account, first) as device:
        device.mark_ready()
        assert (device.path / "prefs.js").read_text() == "synthetic-first"
    assert list(tmp_path.iterdir()) == []


def test_error_snapshots_partial_profile_and_removes_plaintext():
    control = Control()
    original = RuntimeError("synthetic browser failure")
    with pytest.raises(RuntimeError) as caught:
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "prefs.js").write_text("synthetic-progress")
            raise original
    assert caught.value is original
    assert not device.path.exists()
    assert control.saves == 1
    with device_directory({}, control) as device:
        device.mark_ready()
        assert (device.path / "prefs.js").read_text() == "synthetic-progress"


def test_save_failure_preserves_cancellation_and_cleanup():
    control = Control()
    control.fail_save = True
    original = KeyboardInterrupt("synthetic cancellation")
    with pytest.raises(KeyboardInterrupt) as caught:
        with device_directory({}, control) as device:
            device.mark_ready()
            raise original
    assert caught.value is original
    assert not device.path.exists()


def test_normal_save_failure_is_visible_and_plaintext_removed():
    control = Control()
    control.fail_save = True
    with pytest.raises(RuntimeError, match="lease expired"):
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "prefs.js").write_text("synthetic")
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
        ("prefs.js", tarfile.REGTYPE, b"first"),
        ("prefs.js", tarfile.REGTYPE, b"second"),
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
    archive = packed([("prefs.js", tarfile.REGTYPE, b"synthetic" * 100)])
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
    monkeypatch.setattr(browser_device, "MAX_MEMBERS", 2)
    with pytest.raises(DeviceArchiveError, match="member limit"):
        with device_directory({}, Control(archive)):
            pytest.fail("Too many members yielded a directory")
    control = Control()
    with pytest.raises(DeviceArchiveError, match="member limit"):
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "first").touch()
            (device.path / "second").touch()
    assert not device.path.exists()
    assert control.saves == 0


def test_snapshot_rejects_non_transient_symlink():
    control = Control()
    with pytest.raises(DeviceArchiveError, match="Unsupported"):
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "synthetic-link").symlink_to("/synthetic/target")
    assert not device.path.exists()
    assert control.saves == 0


@pytest.mark.parametrize("limit", ["MAX_COMPRESSED_BYTES", "MAX_UNCOMPRESSED_BYTES"])
def test_snapshot_size_limit_cleans_up_without_saving(monkeypatch, limit):
    monkeypatch.setattr(browser_device, limit, 32)
    control = Control()
    with pytest.raises(DeviceArchiveError, match="size limit"):
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "prefs.js").write_bytes(b"synthetic" * 100)
    assert not device.path.exists()
    assert control.saves == 0


def test_truncated_gzip_archive_is_rejected():
    archive = packed([("prefs.js", tarfile.REGTYPE, b"synthetic")])
    with pytest.raises(DeviceArchiveError):
        with device_directory({}, Control(archive[:-8])):
            pytest.fail("Truncated archive yielded a directory")


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("error", [False, True])
def test_startup_failure_or_unready_exit_preserves_archive(restored, error):
    archive = packed([("prefs.js", tarfile.REGTYPE, b"synthetic-old")]) if restored else None
    control = Control(archive)
    original = RuntimeError("synthetic startup or import failure")
    try:
        with device_directory({}, control) as device:
            assert not device.ready
            assert device.restored is restored
            (device.path / "prefs.js").write_text("synthetic-incomplete")
            if error:
                raise original
    except RuntimeError as caught:
        assert error and caught is original
    assert control.saves == 0
    assert control.archive is archive
    assert not device.path.exists()


@pytest.mark.parametrize("error", [False, True])
def test_close_failure_discard_preserves_previous_archive(error):
    archive = packed([("prefs.js", tarfile.REGTYPE, b"synthetic-old")])
    control = Control(archive)
    original = RuntimeError("synthetic browser error")
    try:
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / "prefs.js").write_text("synthetic-progress")
            device.abort_snapshot()
            # Discard is permanent even if another caller marks it ready again.
            device.mark_ready()
            if error:
                raise original
    except RuntimeError as caught:
        assert error and caught is original
    assert control.saves == 0
    assert control.archive is archive
    assert not device.path.exists()


def test_unmarked_chromium_archive_starts_empty_and_is_preserved_until_ready():
    previous = packed([
        ("Local State", tarfile.REGTYPE, b"synthetic-chromium"),
        ("Default/Network/Cookies", tarfile.REGTYPE, b"synthetic-cookie"),
    ], marked=False)
    control = Control(previous)
    with device_directory({}, control) as device:
        assert not device.restored
        assert list(device.path.iterdir()) == []
    assert control.archive is previous
    assert control.saves == 0
    with device_directory({}, control) as device:
        assert not device.restored
        device.mark_ready()
        (device.path / "prefs.js").write_text("synthetic-firefox")
    with device_directory({}, control) as device:
        assert device.restored
        assert (device.path / "prefs.js").read_text() == "synthetic-firefox"
        assert not (device.path / "Default").exists()
        assert not (device.path / "Local State").exists()


@pytest.mark.parametrize("payload", [
    b"invalid-json", b"[]", b'{"engine":"chromium","format":"firefox-profile","version":1}',
    b'{"engine":"camoufox","format":"firefox-profile","version":2}',
    b'{"engine":"camoufox","format":"firefox-profile","version":true}',
])
def test_invalid_or_unsupported_firefox_format_fails_without_replacing_archive(payload):
    previous = packed([
        (browser_device.ARCHIVE_FORMAT_FILE, tarfile.REGTYPE, payload),
        ("prefs.js", tarfile.REGTYPE, b"synthetic"),
    ], marked=False)
    control = Control(previous)
    with pytest.raises(DeviceArchiveError, match="format"):
        with device_directory({}, control):
            pytest.fail("Invalid format yielded a directory")
    assert control.archive is previous
    assert control.saves == 0


@pytest.mark.parametrize("name", ["nested/lock", "cache2", "prefs.js"])
def test_snapshot_rejects_links_outside_known_root_locks(name):
    control = Control()
    with pytest.raises(DeviceArchiveError, match="Unsupported"):
        with device_directory({}, control) as device:
            device.mark_ready()
            path = device.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to("/synthetic/target")
    assert control.saves == 0


def test_snapshot_rejects_special_file_even_when_named_like_transient_lock():
    control = Control()
    with pytest.raises(DeviceArchiveError, match="Unsupported"):
        with device_directory({}, control) as device:
            device.mark_ready()
            os.mkfifo(device.path / "lock")
    assert control.saves == 0


def test_snapshot_reserves_archive_format_marker():
    control = Control()
    with pytest.raises(DeviceArchiveError, match="Reserved"):
        with device_directory({}, control) as device:
            device.mark_ready()
            (device.path / browser_device.ARCHIVE_FORMAT_FILE).write_text("synthetic")
    assert control.saves == 0
