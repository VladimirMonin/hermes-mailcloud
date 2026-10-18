"""Owner-private, atomic storage for public-link capability records."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import _platform
from ._platform import PrivateStorageError
from .core.errors import ErrorKind, ErrorPayload, MailCloudError
from .core.paths import normalize_remote_path
from .rclone.parser import PublicLink

JOURNAL_VERSION = 1
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
LOCK_ACQUIRE_TIMEOUT_SECONDS = 5.0


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
    """Append complete records by atomically replacing a private JSONL file under a lock."""

    path: Path

    def prepare(self) -> None:
        """Reject unsafe paths before cloud side effects can create an unrecorded capability."""
        try:
            _ensure_secure_parent(self.path.parent)
            _assert_private_regular_file(self.path, allow_missing=True)
            with _exclusive_lock(self.path):
                _read_private_journal(self.path)
                _probe_private_storage(self.path.parent)
        except JournalError:
            raise
        except PrivateStorageError as exc:
            raise JournalError(exc.message) from exc
        except OSError as exc:
            raise JournalError() from exc

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
        try:
            with _exclusive_lock(self.path):
                existing = _read_private_journal(self.path)
                separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
                content = existing + separator + encoded_record
                if len(content) > MAX_JOURNAL_BYTES:
                    raise JournalError("local link journal is too large to update safely")
                _atomic_replace(self.path, content)
        except JournalError:
            raise
        except PrivateStorageError as exc:
            raise JournalError(exc.message) from exc
        except OSError as exc:
            raise JournalError() from exc
        return record


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Serialize read-modify-replace journal updates without widening local permissions."""
    lock_path = path.with_name(f".{path.name}.lock")
    with _platform.backend().exclusive_lock(
        lock_path, timeout_seconds=LOCK_ACQUIRE_TIMEOUT_SECONDS
    ):
        yield


def _ensure_secure_parent(parent: Path) -> None:
    _platform.backend().ensure_private_directory(parent)


def _assert_private_regular_file(path: Path, *, allow_missing: bool) -> None:
    _platform.backend().assert_private_regular_file(path, allow_missing=allow_missing)


def _read_private_journal(path: Path) -> bytes:
    backend = _platform.backend()
    try:
        return backend.read_private_bytes(path, max_bytes=MAX_JOURNAL_BYTES)
    except PrivateStorageError as exc:
        if os.name == "posix":
            # A concurrent replace can unlink the inode between open and fstat.
            # Retry once only if the current path is still a valid private file;
            # persistent ACL/owner/reparse/hardlink failures are re-raised below.
            try:
                backend.assert_private_regular_file(path, allow_missing=False)
                return backend.read_private_bytes(path, max_bytes=MAX_JOURNAL_BYTES)
            except PrivateStorageError:
                pass
        raise JournalError(exc.message) from exc


def _atomic_replace(path: Path, content: bytes) -> None:
    try:
        _platform.backend().atomic_write_replace(path, content, max_bytes=MAX_JOURNAL_BYTES)
    except PrivateStorageError as exc:
        raise JournalError(exc.message) from exc


def _probe_private_storage(parent: Path) -> None:
    _platform.backend().probe_private_storage(parent)
