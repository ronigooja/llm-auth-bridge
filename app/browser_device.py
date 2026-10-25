"""Restricted, temporary Chromium profiles backed by encrypted control storage.

Callers must close Chromium before leaving ``device_directory``. The control owns
account binding, encryption, and lease checks; account data never selects paths.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import gzip
import io
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile


MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 20_000
_EXCLUDED = {
    "SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort",
    "Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache",
    "ShaderCache", "CacheStorage", "Crashpad", "Crash Reports", "BrowserMetrics",
}


class DeviceArchiveError(ValueError):
    """A profile archive is malformed, unsafe, or exceeds its resource budget."""


@dataclass
class BrowserDevice:
    path: Path
    restored: bool
    ready: bool = False
    _discarded: bool = False

    def mark_ready(self):
        """Allow saving only after browser startup and legacy state import."""
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
            # Validate all headers before creating any profile contents.
            for member, relative in members:
                target = root.joinpath(*relative.parts)
                if any(part in _EXCLUDED for part in relative.parts):
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
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise DeviceArchiveError("Invalid device archive") from exc


def _snapshot(root):
    output = _LimitedBuffer()

    def walk_error(error):
        raise error

    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=_LimitedWriter(compressed), mode="w|") as archive:
            count = 0
            for directory, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
                directories[:] = sorted(d for d in directories if d not in _EXCLUDED)
                for name in directories + sorted(filenames):
                    if name in _EXCLUDED:
                        continue
                    count += 1
                    if count > MAX_MEMBERS:
                        raise DeviceArchiveError("Device archive exceeds member limit")
                    path = Path(directory) / name
                    metadata = path.lstat()
                    member = tarfile.TarInfo(path.relative_to(root).as_posix())
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

    Call ``mark_ready`` only after startup and legacy import succeed; call
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
        restored = archive is not None
        if restored:
            _restore(archive, root)
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
