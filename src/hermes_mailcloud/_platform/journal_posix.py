"""POSIX owner-private journal storage primitives."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import PrivateStorageError

_READ_CHUNK_BYTES = 64 * 1024
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_ONLY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def _canonical(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError) as exc:
        raise PrivateStorageError("local link journal path is invalid") from exc


def _current_uid() -> int:
    return os.geteuid()


def ensure_private_directory(path: Path) -> None:
    """Create missing components with mode 0700 and verify the final directory."""
    directory = _canonical(path)
    _create_missing_directories(directory)
    _assert_private_directory(directory)


def _create_missing_directories(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while True:
        try:
            information = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise PrivateStorageError(
                    "could not prepare the local link journal directory"
                ) from None
            current = parent
            continue
        except OSError as exc:
            raise PrivateStorageError("could not prepare the local link journal directory") from exc
        if stat.S_ISLNK(information.st_mode) or not stat.S_ISDIR(information.st_mode):
            raise PrivateStorageError("local link journal directory is not secure")
        break

    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise PrivateStorageError("could not prepare the local link journal directory") from exc
        else:
            try:
                os.chmod(directory, 0o700)
            except OSError as exc:
                raise PrivateStorageError(
                    "could not prepare the local link journal directory"
                ) from exc
        _assert_private_directory(directory)


def _assert_private_directory(path: Path) -> None:
    try:
        information = path.lstat()
    except OSError as exc:
        raise PrivateStorageError("could not prepare the local link journal directory") from exc
    if stat.S_ISLNK(information.st_mode) or not stat.S_ISDIR(information.st_mode):
        raise PrivateStorageError("local link journal directory is not secure")
    if information.st_uid != _current_uid() or stat.S_IMODE(information.st_mode) & 0o022:
        raise PrivateStorageError("local link journal directory is not secure")


def _assert_private_file_stat(information: os.stat_result) -> None:
    if (
        stat.S_ISLNK(information.st_mode)
        or not stat.S_ISREG(information.st_mode)
        or stat.S_IMODE(information.st_mode) & 0o077
        or information.st_uid != _current_uid()
        or information.st_nlink != 1
    ):
        raise PrivateStorageError("local link journal is not a private regular file")


def assert_private_regular_file(path: Path, *, allow_missing: bool) -> None:
    file_path = _canonical(path)
    _assert_private_directory(file_path.parent)
    try:
        descriptor = os.open(file_path, os.O_RDONLY | _NO_FOLLOW | _NONBLOCK)
    except FileNotFoundError:
        if allow_missing:
            return
        raise PrivateStorageError("local link journal is not a private regular file") from None
    except OSError as exc:
        raise PrivateStorageError("local link journal is not a private regular file") from exc
    try:
        _assert_private_file_stat(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def read_private_bytes(path: Path, *, max_bytes: int) -> bytes:
    file_path = _canonical(path)
    _assert_private_directory(file_path.parent)
    try:
        descriptor = os.open(file_path, os.O_RDONLY | _NO_FOLLOW | _NONBLOCK)
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise PrivateStorageError("local link journal is not a private regular file") from exc
    try:
        _assert_private_file_stat(os.fstat(descriptor))
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise PrivateStorageError("local link journal is too large to update safely")
            chunks.append(chunk)
        return b"".join(chunks)
    except PrivateStorageError:
        raise
    except OSError as exc:
        raise PrivateStorageError("local link journal could not be read safely") from exc
    finally:
        os.close(descriptor)


@contextmanager
def exclusive_lock(lock_path: Path, *, timeout_seconds: float) -> Iterator[None]:
    """Serialize the whole read-modify-replace cycle on a stable sidecar file."""
    path = _canonical(lock_path)
    _assert_private_directory(path.parent)
    descriptor, created = _open_lock(path)
    try:
        if created:
            try:
                os.fchmod(descriptor, 0o600)
            except OSError as exc:
                raise PrivateStorageError("could not lock the local link journal") from exc
        _assert_private_file_stat(os.fstat(descriptor))
        _acquire(descriptor, timeout_seconds)
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(descriptor)


def _open_lock(path: Path) -> tuple[int, bool]:
    try:
        descriptor = os.open(
            path, os.O_RDWR | os.O_CREAT | os.O_EXCL | _NO_FOLLOW | _NONBLOCK, 0o600
        )
        return descriptor, True
    except FileExistsError:
        pass
    except OSError as exc:
        raise PrivateStorageError("could not lock the local link journal") from exc
    try:
        descriptor = os.open(path, os.O_RDWR | _NO_FOLLOW | _NONBLOCK)
    except OSError as exc:
        raise PrivateStorageError("could not lock the local link journal") from exc
    return descriptor, False


def _acquire(descriptor: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PrivateStorageError(
                    "timed out waiting for the local link journal lock"
                ) from None
            time.sleep(min(0.05, remaining))
        except InterruptedError:
            continue
        except OSError as exc:
            raise PrivateStorageError("could not lock the local link journal") from exc


def atomic_write_replace(path: Path, content: bytes, *, max_bytes: int) -> None:
    """Write a private temporary file, fsync it, replace the journal and fsync its directory."""
    if len(content) > max_bytes:
        raise PrivateStorageError("local link journal is too large to update safely")
    file_path = _canonical(path)
    parent = file_path.parent
    _assert_private_directory(parent)
    temporary_path, descriptor = _create_temporary(parent, file_path.name)
    try:
        _assert_private_file_stat(os.fstat(descriptor))
        try:
            _write_all(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary_path, file_path)
        _fsync_directory(parent)
    except PrivateStorageError:
        raise
    except OSError as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    finally:
        _delete_quietly(temporary_path)
    assert_private_regular_file(file_path, allow_missing=False)


def probe_private_storage(directory: Path) -> None:
    """Prove private create, flush and same-directory replace before cloud side effects."""
    parent = _canonical(directory)
    _assert_private_directory(parent)
    first: Path | None = None
    second: Path | None = None
    try:
        first, first_descriptor = _create_temporary(parent, "probe")
        try:
            os.fsync(first_descriptor)
        finally:
            os.close(first_descriptor)
        second, second_descriptor = _create_temporary(parent, "probe")
        try:
            os.fsync(second_descriptor)
        finally:
            os.close(second_descriptor)
        os.replace(first, second)
        first = None
        _fsync_directory(parent)
    except PrivateStorageError:
        raise
    except OSError as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    finally:
        if first is not None:
            _delete_quietly(first)
        if second is not None:
            _delete_quietly(second)


def _create_temporary(parent: Path, name: str) -> tuple[Path, int]:
    for _ in range(16):
        temporary_path = parent / f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_FOLLOW,
                0o600,
            )
        except FileExistsError:
            continue
        except OSError as exc:
            raise PrivateStorageError("could not securely update the local link journal") from exc
        try:
            os.fchmod(descriptor, 0o600)
        except OSError as exc:
            os.close(descriptor)
            _delete_quietly(temporary_path)
            raise PrivateStorageError("could not securely update the local link journal") from exc
        return temporary_path, descriptor
    raise PrivateStorageError("could not securely update the local link journal")


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("could not write journal record")
        offset += written


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | _DIRECTORY_ONLY)
    except OSError as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    finally:
        os.close(descriptor)


def _delete_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
