"""Native Windows private journal storage using pywin32 security descriptors."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pywintypes
import win32api
import win32con
import win32file
import win32security

from . import PrivateStorageError

_READ_CHUNK_BYTES = 64 * 1024
_ERROR_INVALID_FUNCTION = 1
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_INVALID_HANDLE = 6
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_TRANSIENT_OPEN_ERRORS = frozenset(
    {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND, _ERROR_SHARING_VIOLATION}
)
_TRANSIENT_OPEN_TIMEOUT_SECONDS = 0.05
_TRANSIENT_OPEN_RETRY_SECONDS = 0.002
_INHERITED_ACE = 0x10
_INHERIT_ONLY_ACE = 0x08
_DIRECTORY_INHERITANCE = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
_SHARE_ALL = win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE
_NOT_SUPPORTED_STORAGE = "local link journal requires a local fixed NTFS volume"
_UNSAFE_LINK = "local link journal path uses an unsupported link or alias"
_WIN32_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)


def _reject_win32_alias_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part.endswith((" ", ".")) or ":" in part:
            raise PrivateStorageError(_UNSAFE_LINK)
        base_name = part.split(".", 1)[0].casefold()
        if base_name in _WIN32_RESERVED_NAMES:
            raise PrivateStorageError(_UNSAFE_LINK)
        current = current / part
        long_name = _long_name_if_present(current)
        if long_name is not None and Path(long_name).name.casefold() != part.casefold():
            raise PrivateStorageError(_UNSAFE_LINK)


def _long_name_if_present(path: Path) -> str | None:
    try:
        return win32file.GetLongPathName(str(path))
    except pywintypes.error as exc:
        if exc.winerror in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return None
        raise PrivateStorageError("could not inspect the local link journal path") from exc


def _canonical(path: Path) -> Path:
    try:
        raw = os.fspath(path)
    except (TypeError, ValueError) as exc:
        raise PrivateStorageError("local link journal path is invalid") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PrivateStorageError("local link journal path is invalid")
    if not os.path.isabs(raw):
        raise PrivateStorageError("local link journal path must be absolute")
    if raw.startswith("\\\\"):
        raise PrivateStorageError(_UNSAFE_LINK)
    parsed = Path(raw)
    if not parsed.drive:
        raise PrivateStorageError(_UNSAFE_LINK)
    if ".." in parsed.parts:
        raise PrivateStorageError("local link journal path must be canonical")
    _reject_win32_alias_components(parsed)
    return Path(os.path.abspath(raw))


def _current_user_sid() -> object:
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32file.CloseHandle(token)


def _system_sid() -> object:
    return win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)


def _administrators_sid() -> object:
    return win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None)


def _private_security_attributes(*, directory: bool) -> win32security.SECURITY_ATTRIBUTES:
    user_sid = _current_user_sid()
    dacl = win32security.ACL()
    ace_flags = _DIRECTORY_INHERITANCE if directory else 0
    for sid in (user_sid, _system_sid(), _administrators_sid()):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            ace_flags,
            win32file.FILE_ALL_ACCESS,
            sid,
        )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(user_sid, False)
    descriptor.SetSecurityDescriptorGroup(_system_sid(), False)
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    descriptor.SetSecurityDescriptorControl(
        win32security.SE_DACL_PROTECTED, win32security.SE_DACL_PROTECTED
    )
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = False
    return attributes


def _assert_supported_storage(path: Path) -> None:
    try:
        volume_root = win32file.GetVolumePathName(str(path))
        drive_type = win32file.GetDriveType(volume_root)
        filesystem = win32api.GetVolumeInformation(volume_root)[4]
    except pywintypes.error as exc:
        raise PrivateStorageError(_NOT_SUPPORTED_STORAGE) from exc
    if drive_type != win32con.DRIVE_FIXED or str(filesystem).casefold() != "ntfs":
        raise PrivateStorageError(_NOT_SUPPORTED_STORAGE)


def _file_attributes(path: Path) -> int | None:
    try:
        attributes = win32file.GetFileAttributes(str(path))
    except pywintypes.error as exc:
        if exc.winerror in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return None
        raise PrivateStorageError("could not inspect the local link journal path") from exc
    if attributes == -1:
        error = win32api.GetLastError()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return None
        raise PrivateStorageError("could not inspect the local link journal path")
    return attributes


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        attributes = _file_attributes(current)
        if attributes is None:
            return
        if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PrivateStorageError(_UNSAFE_LINK)
        if not attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
            raise PrivateStorageError("local link journal directory is not secure")


def ensure_private_directory(path: Path) -> None:
    """Create missing levels with protected owner-only DACLs and verify the leaf."""
    directory = _canonical(path)
    _assert_supported_storage(directory)
    _assert_no_reparse_ancestors(directory)
    missing: list[Path] = []
    current = directory
    while True:
        attributes = _file_attributes(current)
        if attributes is None:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise PrivateStorageError(
                    "could not prepare the local link journal directory"
                ) from None
            current = parent
            continue
        if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PrivateStorageError(_UNSAFE_LINK)
        if not attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
            raise PrivateStorageError("local link journal directory is not secure")
        break
    for candidate in reversed(missing):
        _create_private_directory(candidate)
    _assert_private_directory(directory)


def _create_private_directory(path: Path) -> None:
    try:
        win32file.CreateDirectory(str(path), _private_security_attributes(directory=True))
    except pywintypes.error as exc:
        if exc.winerror not in (_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS):
            raise PrivateStorageError("could not prepare the local link journal directory") from exc
    _assert_private_directory(path)


def _open_handle(
    path: Path,
    access: int,
    *,
    directory: bool = False,
    disposition: int = win32con.OPEN_EXISTING,
    attributes: win32security.SECURITY_ATTRIBUTES | None = None,
) -> int:
    flags = win32con.FILE_ATTRIBUTE_NORMAL | win32file.FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= win32con.FILE_FLAG_BACKUP_SEMANTICS
    return win32file.CreateFile(str(path), access, _SHARE_ALL, attributes, disposition, flags, None)


def _assert_private_directory(path: Path) -> None:
    _assert_supported_storage(path)
    _assert_no_reparse_ancestors(path)
    attributes = _file_attributes(path)
    if attributes is None or attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
        raise PrivateStorageError("local link journal directory is not secure")
    if not attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
        raise PrivateStorageError("local link journal directory is not secure")
    try:
        handle = _open_handle(path, win32con.READ_CONTROL, directory=True)
    except pywintypes.error as exc:
        raise PrivateStorageError("local link journal directory is not secure") from exc
    try:
        information = win32file.GetFileInformationByHandle(handle)
        if information[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PrivateStorageError(_UNSAFE_LINK)
        _assert_private_security(handle, directory=True)
    finally:
        win32file.CloseHandle(handle)


def _assert_private_security(handle: int, *, directory: bool) -> None:
    try:
        descriptor = win32security.GetSecurityInfo(
            handle,
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
        )
    except pywintypes.error as exc:
        raise PrivateStorageError("local link journal security could not be verified") from exc

    owner = descriptor.GetSecurityDescriptorOwner()
    if owner is None or not _same_sid(owner, _current_user_sid()):
        raise PrivateStorageError("local link journal is not owned by the current user")
    control = descriptor.GetSecurityDescriptorControl()[0]
    if not control & win32security.SE_DACL_PROTECTED:
        raise PrivateStorageError("local link journal has an inherited or unprotected DACL")
    try:
        dacl = descriptor.GetSecurityDescriptorDacl()
    except pywintypes.error as exc:
        raise PrivateStorageError("local link journal security could not be verified") from exc
    if dacl is None:
        raise PrivateStorageError("local link journal has no private DACL")

    allowed = _allowed_sid_strings()
    owner_string = _sid_string(_current_user_sid())
    owner_ace_seen = False
    for index in range(dacl.GetAceCount()):
        try:
            entry = dacl.GetAce(index)
        except (pywintypes.error, TypeError, ValueError) as exc:
            raise PrivateStorageError(
                "local link journal DACL contains an unsupported ACE"
            ) from exc
        if not isinstance(entry, tuple) or len(entry) != 3:
            raise PrivateStorageError("local link journal DACL contains an unsupported ACE")
        header, mask, sid = entry
        if not isinstance(header, tuple) or len(header) != 2:
            raise PrivateStorageError("local link journal DACL contains an unsupported ACE")
        ace_type, ace_flags = header
        if not all(isinstance(value, int) for value in (ace_type, ace_flags, mask)):
            raise PrivateStorageError("local link journal DACL contains an unsupported ACE")
        if ace_type != win32security.ACCESS_ALLOWED_ACE_TYPE:
            raise PrivateStorageError("local link journal DACL contains an unsupported ACE")
        if ace_flags & (_INHERITED_ACE | _INHERIT_ONLY_ACE):
            raise PrivateStorageError("local link journal DACL contains an inherited ACE")
        sid_string = _sid_string(sid)
        if sid_string not in allowed:
            raise PrivateStorageError("local link journal DACL grants access to another principal")
        if sid_string != owner_string:
            continue
        if not directory and ace_flags & _DIRECTORY_INHERITANCE:
            raise PrivateStorageError("local link journal file DACL contains inheritance flags")
        if mask & win32file.FILE_ALL_ACCESS != win32file.FILE_ALL_ACCESS:
            raise PrivateStorageError("local link journal owner ACE is too narrow")
        if directory and ace_flags & _DIRECTORY_INHERITANCE != _DIRECTORY_INHERITANCE:
            raise PrivateStorageError(
                "local link journal directory owner ACE does not inherit to children"
            )
        owner_ace_seen = True
    if not owner_ace_seen:
        raise PrivateStorageError("local link journal DACL does not grant the owner access")


def _same_sid(left: object, right: object) -> bool:
    try:
        return _sid_string(left) == _sid_string(right)
    except (pywintypes.error, TypeError, ValueError) as exc:
        raise PrivateStorageError("local link journal security could not be verified") from exc


def _sid_string(sid: object) -> str:
    try:
        return win32security.ConvertSidToStringSid(sid)
    except (pywintypes.error, TypeError, ValueError) as exc:
        raise PrivateStorageError("local link journal security could not be verified") from exc


def _allowed_sid_strings() -> set[str]:
    return {
        _sid_string(_current_user_sid()),
        _sid_string(_system_sid()),
        _sid_string(_administrators_sid()),
    }


def _assert_private_file_handle(handle: int) -> None:
    information = win32file.GetFileInformationByHandle(handle)
    attributes = information[0]
    number_of_links = information[7]
    if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
        raise PrivateStorageError(_UNSAFE_LINK)
    if attributes & win32con.FILE_ATTRIBUTE_DIRECTORY or number_of_links != 1:
        raise PrivateStorageError("local link journal is not a private regular file")
    _assert_private_security(handle, directory=False)


def assert_private_regular_file(path: Path, *, allow_missing: bool) -> None:
    file_path = _canonical(path)
    _assert_private_directory(file_path.parent)
    attributes = _file_attributes(file_path)
    if attributes is None:
        if allow_missing:
            return
        raise PrivateStorageError("local link journal is not a private regular file")
    handle = _open_private_file_with_transient_retry(file_path)
    if handle is None:
        if allow_missing:
            return
        raise PrivateStorageError("local link journal is not a private regular file")
    try:
        _assert_private_file_handle(handle)
    finally:
        win32file.CloseHandle(handle)


def _open_private_file_with_transient_retry(path: Path) -> int | None:
    """Retry only bounded native replacement/missing transients, never security failures."""
    deadline = time.monotonic() + _TRANSIENT_OPEN_TIMEOUT_SECONDS
    while True:
        try:
            return _open_handle(
                path,
                win32con.GENERIC_READ | win32con.READ_CONTROL,
            )
        except pywintypes.error as exc:
            if exc.winerror not in _TRANSIENT_OPEN_ERRORS:
                raise PrivateStorageError(
                    "local link journal is not a private regular file"
                ) from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if exc.winerror == _ERROR_SHARING_VIOLATION:
                    raise PrivateStorageError(
                        "local link journal could not be read safely"
                    ) from exc
                return None
            time.sleep(min(_TRANSIENT_OPEN_RETRY_SECONDS, remaining))


def read_private_bytes(path: Path, *, max_bytes: int) -> bytes:
    file_path = _canonical(path)
    _assert_private_directory(file_path.parent)
    handle = _open_private_file_with_transient_retry(file_path)
    if handle is None:
        return b""
    try:
        _assert_private_file_handle(handle)
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                _error, chunk = win32file.ReadFile(handle, _READ_CHUNK_BYTES)
            except pywintypes.error as exc:
                raise PrivateStorageError("local link journal could not be read safely") from exc
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise PrivateStorageError("local link journal is too large to update safely")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        win32file.CloseHandle(handle)


@contextmanager
def exclusive_lock(lock_path: Path, *, timeout_seconds: float) -> Iterator[None]:
    """Hold a stable sidecar file's byte-range lock for the whole read-modify-replace."""
    path = _canonical(lock_path)
    _assert_private_directory(path.parent)
    handle, created = _open_lock(path)
    try:
        _assert_private_file_handle(handle)
        _acquire(handle, timeout_seconds)
        try:
            yield
        finally:
            try:
                win32file.UnlockFileEx(handle, 1, 0, pywintypes.OVERLAPPED())
            except pywintypes.error:
                pass
    finally:
        win32file.CloseHandle(handle)


def _open_lock(path: Path) -> tuple[int, bool]:
    access = win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.READ_CONTROL
    try:
        handle = _open_handle(
            path,
            access,
            disposition=win32con.CREATE_NEW,
            attributes=_private_security_attributes(directory=False),
        )
        return handle, True
    except pywintypes.error as exc:
        if exc.winerror not in (_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS):
            raise PrivateStorageError("could not lock the local link journal") from exc
    try:
        handle = _open_handle(path, access)
    except pywintypes.error as exc:
        raise PrivateStorageError("could not lock the local link journal") from exc
    return handle, False


def _acquire(handle: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            win32file.LockFileEx(
                handle,
                win32con.LOCKFILE_EXCLUSIVE_LOCK | win32con.LOCKFILE_FAIL_IMMEDIATELY,
                1,
                0,
                pywintypes.OVERLAPPED(),
            )
            return
        except pywintypes.error as exc:
            if exc.winerror in (_ERROR_LOCK_VIOLATION, _ERROR_SHARING_VIOLATION):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PrivateStorageError(
                        "timed out waiting for the local link journal lock"
                    ) from exc
                time.sleep(min(0.05, remaining))
                continue
            raise PrivateStorageError("could not lock the local link journal") from exc


def atomic_write_replace(path: Path, content: bytes, *, max_bytes: int) -> None:
    """Flush a private temporary file, replace the journal and flush directory metadata."""
    if len(content) > max_bytes:
        raise PrivateStorageError("local link journal is too large to update safely")
    file_path = _canonical(path)
    parent = file_path.parent
    _assert_private_directory(parent)
    assert_private_regular_file(file_path, allow_missing=True)
    temporary_path, handle = _create_temporary(parent, file_path.name)
    try:
        _assert_private_file_handle(handle)
        _write_all(handle, content)
        win32file.FlushFileBuffers(handle)
        win32file.CloseHandle(handle)
        handle = 0
        _replace_file(str(temporary_path), str(file_path))
        _flush_directory(parent)
    except PrivateStorageError:
        raise
    except pywintypes.error as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    finally:
        if handle:
            try:
                win32file.CloseHandle(handle)
            except pywintypes.error:
                pass
        _delete_quietly(temporary_path)
    assert_private_regular_file(file_path, allow_missing=False)


def probe_private_storage(directory: Path) -> None:
    """Prove protected create, flush and same-directory replacement before cloud effects."""
    parent = _canonical(directory)
    _assert_private_directory(parent)
    first: Path | None = None
    second: Path | None = None
    try:
        first, first_handle = _create_temporary(parent, "probe")
        try:
            win32file.FlushFileBuffers(first_handle)
        finally:
            win32file.CloseHandle(first_handle)
        second, second_handle = _create_temporary(parent, "probe")
        try:
            win32file.FlushFileBuffers(second_handle)
        finally:
            win32file.CloseHandle(second_handle)
        _replace_file(str(first), str(second))
        first = None
        assert_private_regular_file(second, allow_missing=False)
        _flush_directory(parent)
    except PrivateStorageError:
        raise
    except pywintypes.error as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    finally:
        if first is not None:
            _delete_quietly(first)
        if second is not None:
            _delete_quietly(second)


def _create_temporary(parent: Path, name: str) -> tuple[Path, int]:
    access = win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.READ_CONTROL
    for _ in range(16):
        temporary_path = parent / f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            handle = _open_handle(
                temporary_path,
                access,
                disposition=win32con.CREATE_NEW,
                attributes=_private_security_attributes(directory=False),
            )
        except pywintypes.error as exc:
            if exc.winerror in (_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS):
                continue
            raise PrivateStorageError("could not securely update the local link journal") from exc
        return temporary_path, handle
    raise PrivateStorageError("could not securely update the local link journal")


def _write_all(handle: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        _error, written = win32file.WriteFile(handle, content[offset:])
        if written <= 0:
            raise PrivateStorageError("could not securely update the local link journal")
        offset += written


def _replace_file(source: str, destination: str) -> None:
    # ReplaceFile(replacement, replaced, ...) keeps concurrent read handles usable.
    if _file_attributes(Path(destination)) is None:
        win32file.MoveFileEx(source, destination, win32file.MOVEFILE_WRITE_THROUGH)
        return
    win32file.ReplaceFile(source, destination, None, 0)


def _flush_directory(path: Path) -> None:
    try:
        handle = _open_handle(
            path,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            directory=True,
        )
    except pywintypes.error as exc:
        raise PrivateStorageError("could not securely update the local link journal") from exc
    try:
        try:
            win32file.FlushFileBuffers(handle)
        except pywintypes.error as exc:
            if exc.winerror not in (_ERROR_INVALID_FUNCTION, _ERROR_INVALID_HANDLE):
                raise PrivateStorageError(
                    "could not securely update the local link journal"
                ) from exc
    finally:
        win32file.CloseHandle(handle)


def _delete_quietly(path: Path) -> None:
    try:
        win32file.DeleteFile(str(path))
    except pywintypes.error:
        pass
