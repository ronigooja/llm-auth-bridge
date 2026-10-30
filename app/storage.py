"""Startup checks for SQLite and process-lock storage."""

from dataclasses import dataclass
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

NETWORK_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "davfs",
        "fuse.sshfs",
        "glusterfs",
        "lustre",
        "nfs",
        "nfs4",
        "smb3",
        "smb",
        "smbfs",
        "sshfs",
    }
)


@dataclass(frozen=True)
class StorageCheck:
    warnings: tuple[str, ...] = ()


def _unescape_mountinfo(value):
    return value.replace(r"\040", " ").replace(r"\011", "\t").replace(r"\134", "\\")


def _mounts(mountinfo):
    result = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        filesystem = after.split()
        if not separator or len(fields) < 6 or not filesystem:
            continue
        try:
            mount_id = int(fields[0])
        except ValueError:
            continue
        result.append((
            mount_id,
            Path(_unescape_mountinfo(fields[4])),
            filesystem[0].lower(),
        ))
    return result


def _mount_for(path, mounts):
    matches = [mount for mount in mounts if path.is_relative_to(mount[1])]
    return max(matches, key=lambda mount: len(mount[1].parts), default=None)


def _mode(settings):
    value = settings.storage_check.lower()
    return value if value in {"warn", "fail", "off"} else "warn"


def check_storage(settings, mountinfo_path=Path("/proc/self/mountinfo")):
    """Return warnings for storage layouts that cannot safely share a lock."""
    if _mode(settings) == "off":
        return StorageCheck()
    try:
        mountinfo = mountinfo_path.read_text()
    except (OSError, UnicodeError):
        return StorageCheck()
    mounts = _mounts(mountinfo)
    if not mounts:
        return StorageCheck()

    try:
        database_parent = settings.db_path.parent.resolve()
        lock_parent = settings.browser_lock.parent.resolve()
    except (OSError, RuntimeError):
        return StorageCheck()
    database_mount = _mount_for(database_parent, mounts)
    lock_mount = _mount_for(lock_parent, mounts)
    warnings = []
    for label, mount in (("database", database_mount), ("browser lock", lock_mount)):
        if mount and mount[2] in NETWORK_FILESYSTEMS:
            warnings.append(
                f"{label} path is on unsupported network filesystem {mount[2]}"
            )
    if database_mount and lock_mount and database_mount[0] != lock_mount[0]:
        warnings.append("database and browser lock are on different filesystem volumes")
    return StorageCheck(tuple(warnings))


def warn_storage_check(result):
    for warning in result.warnings:
        logger.warning("Storage check: %s", warning)
