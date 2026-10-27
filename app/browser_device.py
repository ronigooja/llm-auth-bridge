"""Restricted, temporary Firefox profiles backed by encrypted control storage.

Callers must close Camoufox before leaving ``device_directory``. The control owns
account binding, encryption, and lease checks; account data never selects paths.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile


MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 20_000
ARCHIVE_FORMAT_FILE = ".bridge-firefox-archive.json"
ARCHIVE_FORMAT = {"engine": "camoufox", "format": "firefox-profile", "version": 1}
# When snapshotting a Firefox profile, omit only these known root-level
# transient entries. Unknown links and special files must still be rejected.
_TRANSIENT_LOCKS = {"lock", ".parentlock", "parent.lock"}
_TRANSIENT_DIRECTORIES = {"cache2", "startupCache", "shader-cache", "minidumps", "crashes"}


def _excluded(relative):
    return relative.parts[0] in (_TRANSIENT_LOCKS | _TRANSIENT_DIRECTORIES)


class DeviceArchiveError(ValueError):
    """A profile archive is malformed, unsafe, or exceeds its resource budget."""


@dataclass
class BrowserDevice:
    path: Path
    restored: bool
    ready: bool = False
    _discarded: bool = False

    def mark_ready(self):
        """Allow saving only after browser startup and session restoration."""
        self.ready = True

    def abort_snapshot(self):
        """Keep the previous archive when browser shutdown was not confirmed."""
        self._discarded = True

    @property
    def can_save(self):
        return self.ready and not self._discarded


class _LimitedBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_COMPRESSED_BYTES:
            raise DeviceArchiveError("Device archive exceeds compressed size limit")
        return super().write(data)


class _LimitedWriter:
    def __init__(self, stream):
        self.stream = stream
        self.size = 0

    def write(self, data):
        self.size += len(data)
        if self.size > MAX_UNCOMPRESSED_BYTES:
            raise DeviceArchiveError("Device archive exceeds uncompressed size limit")
        return self.stream.write(data)


def _member_path(name):
    # Do not silently normalize aliases: they can conceal duplicate targets.
    parts = name.rstrip("/").split("/")
    if (not name or name.startswith("/") or "\\" in name
            or any(part in ("", ".", "..") for part in parts)):
        raise DeviceArchiveError("Unsafe device archive path")
    return PurePosixPath(*parts)


def _restore(archive, root):
    if not isinstance(archive, bytes) or len(archive) > MAX_COMPRESSED_BYTES:
        raise DeviceArchiveError("Invalid device archive or compressed size limit")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as compressed:
            raw = compressed.read(MAX_UNCOMPRESSED_BYTES + 1)
        if len(raw) > MAX_UNCOMPRESSED_BYTES:
            raise DeviceArchiveError("Device archive exceeds uncompressed size limit")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as source:
            seen = set()
            members = []
            total = 0
            for member in source:
                if len(members) >= MAX_MEMBERS:
                    raise DeviceArchiveError("Device archive exceeds member limit")
                relative = _member_path(member.name)
                if relative in seen:
                    raise DeviceArchiveError("Duplicate device archive path")
                seen.add(relative)
                if not (member.isdir() or member.isreg()) or member.sparse is not None:
                    raise DeviceArchiveError("Unsupported device archive member")
                if member.size < 0 or (member.isdir() and member.size):
                    raise DeviceArchiveError("Invalid device archive member size")
                total += member.size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise DeviceArchiveError("Device archive exceeds content size limit")
                members.append((member, relative))
            # Validate all headers and the format before creating any profile
            # contents. Unmarked Chromium archives are retained by the control,
            # but their data is never imported into a Firefox profile.
            formats = [(member, relative) for member, relative in members
                       if relative.as_posix() == ARCHIVE_FORMAT_FILE]
            if not formats:
                return False
            marker, _ = formats[0]
            if not marker.isreg() or marker.size > 1024:
                raise DeviceArchiveError("Invalid Firefox device archive format")
            try:
                with source.extractfile(marker) as incoming:
                    value = json.load(incoming)
                if (value != ARCHIVE_FORMAT or not isinstance(value, dict)
                        or type(value.get("version")) is not int):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise DeviceArchiveError("Unsupported Firefox device archive format") from None
            for member, relative in members:
                target = root.joinpath(*relative.parts)
                if relative.as_posix() == ARCHIVE_FORMAT_FILE or _excluded(relative):
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if member.isdir():
                    target.mkdir(mode=0o700, exist_ok=True)
                else:
                    with source.extractfile(member) as incoming:
                        with target.open("xb") as outgoing:
                            os.chmod(target, 0o600)
                            remaining = member.size
                            while remaining:
                                data = incoming.read(min(1024 * 1024, remaining))
                                if not data:
                                    raise DeviceArchiveError("Truncated device archive member")
                                outgoing.write(data)
                                remaining -= len(data)
            return True
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise DeviceArchiveError("Invalid device archive") from exc


def _snapshot(root):
    output = _LimitedBuffer()

    def walk_error(error):
        raise error

    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=_LimitedWriter(compressed), mode="w|") as archive:
            payload = json.dumps(ARCHIVE_FORMAT, sort_keys=True).encode()
            marker = tarfile.TarInfo(ARCHIVE_FORMAT_FILE)
            marker.size = len(payload)
            marker.mode = 0o600
            archive.addfile(marker, io.BytesIO(payload))
            count = 1
            for directory, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
                directories[:] = sorted(directories)
                for name in directories + sorted(filenames):
                    path = Path(directory) / name
                    relative = path.relative_to(root)
                    metadata = path.lstat()
                    is_lock = len(relative.parts) == 1 and name in _TRANSIENT_LOCKS
                    if stat.S_ISLNK(metadata.st_mode) and is_lock:
                        continue
                    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                        raise DeviceArchiveError("Unsupported device profile file")
                    if relative.as_posix() == ARCHIVE_FORMAT_FILE:
                        raise DeviceArchiveError("Reserved device archive format path")
                    if _excluded(relative):
                        if name in directories:
                            directories.remove(name)
                        continue
                    count += 1
                    if count > MAX_MEMBERS:
                        raise DeviceArchiveError("Device archive exceeds member limit")
                    member = tarfile.TarInfo(relative.as_posix())
                    member.mtime = int(metadata.st_mtime)
                    if stat.S_ISDIR(metadata.st_mode):
                        member.type = tarfile.DIRTYPE
                        member.mode = 0o700
                        archive.addfile(member)
                    elif stat.S_ISREG(metadata.st_mode):
                        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as incoming:
                            metadata = os.fstat(incoming.fileno())
                            if not stat.S_ISREG(metadata.st_mode):
                                raise DeviceArchiveError("Unsupported device profile file")
                            if metadata.st_size > MAX_UNCOMPRESSED_BYTES:
                                raise DeviceArchiveError("Device profile file exceeds size limit")
                            member.size = metadata.st_size
                            member.mode = 0o600
                            archive.addfile(member, incoming)
                    else:
                        raise DeviceArchiveError("Unsupported device profile file")
    return output.getvalue()


@contextmanager
def device_directory(account: dict, control):
    """Restore a profile, then save after the caller closes its browser.

    When an archive has no Firefox format marker, start an empty profile and
    preserve the previous archive until a successful snapshot replaces it.
    Call ``mark_ready`` only after startup and session restoration succeed; call
    ``abort_snapshot`` when browser shutdown fails. Only a ready, undiscarded profile
    is saved. Exceptional exits preserve the original error, including
    cancellation and lease failure. Plaintext is always removed. Production
    must mount /tmp as tmpfs.
    """
    del account  # Control alone determines account ownership and persistence.
    with tempfile.TemporaryDirectory(prefix="llm-device-", dir="/tmp") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        archive = control.load_device()
        restored = _restore(archive, root) if archive is not None else False
        device = BrowserDevice(root, restored)
        try:
            yield device
        except BaseException:
            if device.can_save:
                try:
                    control.save_device(_snapshot(root))
                except BaseException:
                    pass
            raise
        else:
            if device.can_save:
                control.save_device(_snapshot(root))
