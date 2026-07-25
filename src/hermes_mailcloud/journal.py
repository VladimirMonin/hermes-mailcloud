"""Owner-private, atomic storage for public-link capability records."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .core.errors import ErrorKind, ErrorPayload, MailCloudError
from .core.paths import normalize_remote_path
from .rclone.parser import PublicLink

JOURNAL_VERSION = 1
MAX_JOURNAL_BYTES = 8 * 1024 * 1024


class JournalError(MailCloudError):
    """A safe journal failure that never exposes its private contents or location."""

    def __init__(self, message: str = "could not securely update the local link journal") -> None:
        super().__init__(ErrorPayload(ErrorKind.UNKNOWN_ERROR, message))


@dataclass(frozen=True, slots=True)
class JournalRecord:
    """Minimal owner-private metadata retained after a successful public-link operation."""

    version: int
    recorded_at: str
    operation: str
    remote_path: str
    public_url: str
    public_url_fingerprint: str

    def to_payload(self) -> dict[str, object]:
        """Return the private JSONL record; callers must never emit this mapping as diagnostics."""
        return {
            "version": self.version,
            "recorded_at": self.recorded_at,
            "operation": self.operation,
            "remote_path": self.remote_path,
            "public_url": self.public_url,
            "public_url_fingerprint": self.public_url_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class LinkJournal:
    """Append complete records by atomically replacing a mode-600 JSONL file under a lock."""

    path: Path

    def prepare(self) -> None:
        """Reject unsafe paths before cloud side effects can create an unrecorded capability."""
        _ensure_secure_parent(self.path.parent)
        _assert_private_regular_file(self.path, allow_missing=True)
        with _exclusive_lock(self.path):
            _read_private_journal(self.path)

    def record(self, operation: str, remote_path: str, public_link: PublicLink) -> JournalRecord:
        """Persist one parsed capability only after the rclone link command succeeds."""
        if operation not in {"publish", "link"}:
            raise ValueError("journal operation must be publish or link")
        if not isinstance(public_link, PublicLink):
            raise ValueError("journal records require a parsed public link")

        self.prepare()
        record = JournalRecord(
            version=JOURNAL_VERSION,
            recorded_at=datetime.now(UTC).isoformat(),
            operation=operation,
            remote_path=normalize_remote_path(remote_path),
            public_url=public_link.url,
            public_url_fingerprint=public_link.fingerprint,
        )
        serialized_record = json.dumps(
            record.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        encoded_record = serialized_record.encode("utf-8") + b"\n"
        with _exclusive_lock(self.path):
            existing = _read_private_journal(self.path)
            separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
            _atomic_replace(self.path, existing + separator + encoded_record)
        return record


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Serialize read-modify-replace journal updates without widening local permissions."""
    lock_path = path.with_name(f".{path.name}.lock")
    _assert_private_regular_file(lock_path, allow_missing=True)
    flags = os.O_RDWR | os.O_CREAT | _no_follow_flag()
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise JournalError() from exc
    try:
        _assert_private_regular_stat(os.fstat(descriptor))
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except JournalError:
        raise
    except OSError as exc:
        raise JournalError() from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def _ensure_secure_parent(parent: Path) -> None:
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        information = parent.lstat()
    except OSError as exc:
        raise JournalError("could not prepare the local link journal directory") from exc
    if (
        stat.S_ISLNK(information.st_mode)
        or not stat.S_ISDIR(information.st_mode)
        or stat.S_IMODE(information.st_mode) & 0o022
    ):
        raise JournalError("local link journal directory is not secure")


def _assert_private_regular_file(path: Path, *, allow_missing: bool) -> None:
    try:
        information = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise JournalError() from None
    except OSError as exc:
        raise JournalError() from exc
    _assert_private_regular_stat(information)


def _assert_private_regular_stat(information: os.stat_result) -> None:
    if (
        stat.S_ISLNK(information.st_mode)
        or not stat.S_ISREG(information.st_mode)
        or stat.S_IMODE(information.st_mode) & 0o077
    ):
        raise JournalError("local link journal is not a private regular file")


def _read_private_journal(path: Path) -> bytes:
    flags = os.O_RDONLY | _no_follow_flag()
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise JournalError() from exc
    try:
        information = os.fstat(descriptor)
        _assert_private_regular_stat(information)
        if information.st_size > MAX_JOURNAL_BYTES:
            raise JournalError("local link journal is too large to update safely")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except JournalError:
        raise
    except OSError as exc:
        raise JournalError() from exc
    finally:
        os.close(descriptor)


def _atomic_replace(path: Path, content: bytes) -> None:
    temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _no_follow_flag()
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_path, flags, 0o600)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise JournalError() from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("could not write journal record")
        offset += written


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise JournalError() from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _no_follow_flag() -> int:
    return getattr(os, "O_NOFOLLOW", 0)
