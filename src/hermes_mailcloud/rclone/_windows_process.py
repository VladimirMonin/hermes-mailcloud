"""Private Windows process boundary: suspended creation, Job containment and bounded I/O.

The caller supplies an already resolved absolute .exe argv and an explicit environment.
This module does not resolve config, invoke a shell, or change the process token. Only the
three standard handles are inherited; the unnamed KILL_ON_JOB_CLOSE Job is never inherited.
A single owner polls both pipes, so no blocking reader threads can outlive a timeout.

The small ctypes bridge is needed because pywin32 STARTUPINFO has no lpAttributeList:
https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-startupinfoexw
https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
https://learn.microsoft.com/windows/win32/procthread/job-objects
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

import win32job

from ..core.errors import ErrorKind, ErrorPayload, MailCloudError

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_HANDLE_FLAG_INHERIT = 0x00000001
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ_WRITE = 0x00000003
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_INSUFFICIENT_BUFFER = 122
_PIPE_EOF_ERRORS = frozenset({109, 232, 233})
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_READ_CHUNK_BYTES = 64 * 1024
_POLL_SECONDS = 0.005
_TERMINATED_EXIT_CODE = 1


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _Kernel32:
    """Documented Win32 signatures; no subprocess.Popen internals are used."""

    def __init__(self) -> None:
        library = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p
        dword_pointer = ctypes.POINTER(wintypes.DWORD)
        handle_pointer = ctypes.POINTER(wintypes.HANDLE)
        size_pointer = ctypes.POINTER(ctypes.c_size_t)
        self.CreateJobObjectW = self._bind(
            library,
            "CreateJobObjectW",
            [pointer, wintypes.LPCWSTR],
            wintypes.HANDLE,
        )
        self.CreatePipe = self._bind(
            library,
            "CreatePipe",
            [handle_pointer, handle_pointer, ctypes.POINTER(_SecurityAttributes), wintypes.DWORD],
            wintypes.BOOL,
        )
        self.CreateFileW = self._bind(
            library,
            "CreateFileW",
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                pointer,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ],
            wintypes.HANDLE,
        )
        self.SetHandleInformation = self._bind(
            library,
            "SetHandleInformation",
            [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD],
            wintypes.BOOL,
        )
        self.CloseHandle = self._bind(library, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
        self.InitializeProcThreadAttributeList = self._bind(
            library,
            "InitializeProcThreadAttributeList",
            [pointer, wintypes.DWORD, wintypes.DWORD, size_pointer],
            wintypes.BOOL,
        )
        self.UpdateProcThreadAttribute = self._bind(
            library,
            "UpdateProcThreadAttribute",
            [
                pointer,
                wintypes.DWORD,
                ctypes.c_size_t,
                pointer,
                ctypes.c_size_t,
                pointer,
                size_pointer,
            ],
            wintypes.BOOL,
        )
        self.DeleteProcThreadAttributeList = self._bind(
            library,
            "DeleteProcThreadAttributeList",
            [pointer],
            None,
        )
        self.CreateProcessW = self._bind(
            library,
            "CreateProcessW",
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                pointer,
                pointer,
                wintypes.BOOL,
                wintypes.DWORD,
                pointer,
                wintypes.LPCWSTR,
                pointer,
                ctypes.POINTER(_ProcessInformation),
            ],
            wintypes.BOOL,
        )
        self.ResumeThread = self._bind(library, "ResumeThread", [wintypes.HANDLE], wintypes.DWORD)
        self.TerminateProcess = self._bind(
            library,
            "TerminateProcess",
            [wintypes.HANDLE, wintypes.UINT],
            wintypes.BOOL,
        )
        self.WaitForSingleObject = self._bind(
            library,
            "WaitForSingleObject",
            [wintypes.HANDLE, wintypes.DWORD],
            wintypes.DWORD,
        )
        self.GetExitCodeProcess = self._bind(
            library,
            "GetExitCodeProcess",
            [wintypes.HANDLE, dword_pointer],
            wintypes.BOOL,
        )
        self.PeekNamedPipe = self._bind(
            library,
            "PeekNamedPipe",
            [wintypes.HANDLE, pointer, wintypes.DWORD, dword_pointer, dword_pointer, dword_pointer],
            wintypes.BOOL,
        )
        self.ReadFile = self._bind(
            library,
            "ReadFile",
            [wintypes.HANDLE, pointer, wintypes.DWORD, dword_pointer, pointer],
            wintypes.BOOL,
        )

    @staticmethod
    def _bind(library: object, name: str, arguments: list[object], result: object) -> object:
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
        return function


_KERNEL = _Kernel32()


class WindowsProcessError(MailCloudError):
    """Safe frozen-kind process error, containing neither argv nor native diagnostics."""


@dataclass(frozen=True, slots=True)
class WindowsProcessResult:
    """Bounded capture ready for the runner's existing result/error parsing seam."""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False


@dataclass(slots=True)
class _Handle:
    value: int | None

    def close(self) -> None:
        if self.value is not None:
            _close_handle(self.value)
            self.value = None


@dataclass(slots=True)
class _Job:
    handle: int | None

    def close(self) -> None:
        if self.handle is not None:
            _close_handle(self.handle)
            self.handle = None


@dataclass(frozen=True, slots=True)
class _CreatedProcess:
    process_handle: int
    thread_handle: int
    pid: int


@dataclass(slots=True)
class _Capture:
    limit: int
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        remaining = self.limit - len(self.data)
        self.data.extend(chunk[: max(0, remaining)])
        self.truncated |= len(chunk) > remaining

    @property
    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


@dataclass(slots=True)
class _PipeCapture:
    handle: _Handle
    capture: _Capture
    eof: bool = False

    def pump(self) -> bool:
        if self.eof:
            return False
        chunk = _read_pipe(self.handle.value)
        if chunk is None:
            self.eof = True
            return True
        self.capture.append(chunk)
        return bool(chunk)


@dataclass(slots=True)
class _Resources:
    handles: list[_Handle] = field(default_factory=list)
    child_handles: list[_Handle] = field(default_factory=list)
    pipes: list[_PipeCapture] = field(default_factory=list)
    job: _Job | None = None
    process: _Handle | None = None
    assigned: bool = False

    def own(self, value: int) -> _Handle:
        handle = _Handle(value)
        self.handles.append(handle)
        return handle


class _DeadlineExpired(Exception):
    pass


def run_windows_process(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_capture_bytes: int,
    cleanup_timeout_seconds: float = 1.0,
) -> WindowsProcessResult:
    """Run one literal executable tree; no return or timeout claims unconfirmed cleanup.

    Only a resolved absolute .exe is accepted. Environment filtering belongs to the
    existing runner; this layer copies exactly the explicit mapping, never os.environ.
    Parent exit is not completion while any Job member or inherited pipe remains alive.
    """
    argv, copied_environment = _validate_inputs(
        command, environment, timeout_seconds, max_capture_bytes, cleanup_timeout_seconds
    )
    started = time.monotonic()
    resources = _Resources()
    result: WindowsProcessResult | None = None
    error: ErrorPayload | None = None
    interruption: BaseException | None = None
    stage = "setup"
    try:
        resources.job = _create_job()
        for _ in range(2):
            read_handle, write_handle = _create_pipe()
            reader = resources.own(read_handle)
            writer = resources.own(write_handle)
            resources.child_handles.append(writer)
            resources.pipes.append(_PipeCapture(reader, _Capture(max_capture_bytes)))
        stdin = resources.own(_create_null_input())
        resources.child_handles.append(stdin)
        stage = "create"
        created = _create_process(
            argv,
            copied_environment,
            stdin.value,
            resources.child_handles[0].value,
            resources.child_handles[1].value,
        )
        resources.process = resources.own(created.process_handle)
        thread = resources.own(created.thread_handle)
        stage = "assign"
        _assign_job(resources.job, resources.process.value)
        resources.assigned = True
        # The child's copies exist already; the parent's write handles must not retain EOF.
        for handle in resources.child_handles:
            handle.close()
        stage = "resume"
        _resume_thread(thread.value)
        thread.close()
        stage = "capture"
        returncode = _capture_until_exit(resources, started + timeout_seconds)
        stdout, stderr = (pipe.capture for pipe in resources.pipes)
        result = WindowsProcessResult(
            returncode,
            stdout.text,
            stderr.text,
            int((time.monotonic() - started) * 1000),
            stdout.truncated,
            stderr.truncated,
        )
    except _DeadlineExpired:
        error = ErrorPayload(
            ErrorKind.TIMEOUT, "rclone command timed out", {"timeout_seconds": timeout_seconds}
        )
    except Exception as exc:
        if stage == "create" and getattr(exc, "winerror", None) in (2, 3):
            error = ErrorPayload(ErrorKind.RCLONE_NOT_FOUND, "rclone executable was not found")
        else:
            error = ErrorPayload(ErrorKind.UNKNOWN_ERROR, "rclone process could not be supervised")
    except BaseException as exc:
        interruption = exc
    finally:
        cleanup_ok = _finish(resources, terminate=result is None, timeout=cleanup_timeout_seconds)
    if interruption is not None:
        raise interruption
    if not cleanup_ok:
        error = ErrorPayload(
            ErrorKind.UNKNOWN_ERROR, "rclone process cleanup could not be confirmed"
        )
    if error is not None:
        raise WindowsProcessError(error) from None
    assert result is not None
    return result


def _validate_inputs(
    command: Sequence[str],
    environment: Mapping[str, str],
    timeout: float,
    capture_limit: int,
    cleanup_timeout: float,
) -> tuple[tuple[str, ...], dict[str, str]]:
    if isinstance(command, (str, bytes)):
        raise ValueError("native process command must be a literal argv sequence")
    argv = tuple(command)
    if not argv or any(not isinstance(value, str) or "\x00" in value for value in argv):
        raise ValueError("native process command must contain strings without NUL")
    if not os.path.isabs(argv[0]) or Path(argv[0]).suffix.casefold() != ".exe":
        raise ValueError("native process executable must be a resolved absolute .exe path")
    for value in (timeout, cleanup_timeout):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("process deadlines must be positive finite numbers")
        if not math.isfinite(value) or value <= 0:
            raise ValueError("process deadlines must be positive finite numbers")
    if isinstance(capture_limit, bool) or not isinstance(capture_limit, int) or capture_limit < 1:
        raise ValueError("max_capture_bytes must be a positive integer")
    copied: dict[str, str] = {}
    folded: set[str] = set()
    for key, value in environment.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\x00" in key
            or not isinstance(value, str)
            or "\x00" in value
            or key.upper() in folded
        ):
            raise ValueError("native process environment is invalid")
        folded.add(key.upper())
        copied[key] = value
    if len(subprocess.list2cmdline(argv)) >= 32767:
        raise ValueError("native process command is too long")
    return argv, copied


def _native_error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


def _close_handle(handle: int) -> None:
    if not _KERNEL.CloseHandle(handle):
        raise _native_error()


def _set_inheritable(handle: int, inheritable: bool) -> None:
    if not _KERNEL.SetHandleInformation(
        handle, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT if inheritable else 0
    ):
        raise _native_error()


def _create_pipe() -> tuple[int, int]:
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    reader, writer = wintypes.HANDLE(), wintypes.HANDLE()
    if not _KERNEL.CreatePipe(
        ctypes.byref(reader), ctypes.byref(writer), ctypes.byref(attributes), 0
    ):
        raise _native_error()
    try:
        _set_inheritable(reader.value, False)
    except BaseException:
        _close_handle(reader.value)
        _close_handle(writer.value)
        raise
    return reader.value, writer.value


def _create_null_input() -> int:
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    handle = _KERNEL.CreateFileW(
        "NUL",
        _GENERIC_READ,
        _FILE_SHARE_READ_WRITE,
        ctypes.byref(attributes),
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle in (None, _INVALID_HANDLE):
        raise _native_error()
    return handle


@contextmanager
def _inherited_handle_list(handles: Sequence[int]) -> Iterator[ctypes.c_void_p]:
    size = ctypes.c_size_t()
    _KERNEL.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or not size.value:
        raise _native_error()
    storage = ctypes.create_string_buffer(size.value)
    attribute_list = ctypes.cast(storage, ctypes.c_void_p)
    if not _KERNEL.InitializeProcThreadAttributeList(attribute_list, 1, 0, ctypes.byref(size)):
        raise _native_error()
    # Both buffers remain alive until DeleteProcThreadAttributeList after CreateProcessW.
    inherited = (wintypes.HANDLE * len(handles))(*handles)
    try:
        if not _KERNEL.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(inherited, ctypes.c_void_p),
            ctypes.sizeof(inherited),
            None,
            None,
        ):
            raise _native_error()
        yield attribute_list
    finally:
        _KERNEL.DeleteProcThreadAttributeList(attribute_list)


def _create_process(
    argv: Sequence[str],
    environment: Mapping[str, str],
    stdin: int,
    stdout: int,
    stderr: int,
) -> _CreatedProcess:
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    environment_text = (
        "\0".join(
            f"{key}={value}"
            for key, value in sorted(environment.items(), key=lambda item: item[0].upper())
        )
        + "\0"
    )
    environment_block = ctypes.create_unicode_buffer(environment_text)
    startup = _StartupInfoEx()
    startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
    startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = stdin
    startup.StartupInfo.hStdOutput = stdout
    startup.StartupInfo.hStdError = stderr
    information = _ProcessInformation()
    with _inherited_handle_list((stdin, stdout, stderr)) as attributes:
        startup.lpAttributeList = attributes.value
        if not _KERNEL.CreateProcessW(
            argv[0],
            command_line,
            None,
            None,
            True,
            _CREATE_SUSPENDED
            | _CREATE_UNICODE_ENVIRONMENT
            | _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_NO_WINDOW,
            environment_block,
            None,
            ctypes.byref(startup),
            ctypes.byref(information),
        ):
            raise _native_error()
    return _CreatedProcess(information.hProcess, information.hThread, information.dwProcessId)


def _create_job() -> _Job:
    # A literal NULL name creates an unnamed object. pywin32 312 rejects None
    # for this argument, so retain exact Win32 semantics in the narrow bridge.
    handle = _KERNEL.CreateJobObjectW(None, None)
    if not handle:
        raise _native_error()
    try:
        _set_inheritable(int(handle), False)
        information = win32job.QueryInformationJobObject(
            handle, win32job.JobObjectExtendedLimitInformation
        )
        information["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            handle, win32job.JobObjectExtendedLimitInformation, information
        )
    except BaseException:
        _close_handle(handle)
        raise
    return _Job(handle)


def _assign_job(job: _Job, process: int) -> None:
    win32job.AssignProcessToJobObject(job.handle, process)


def _resume_thread(thread: int) -> None:
    if _KERNEL.ResumeThread(thread) == 0xFFFFFFFF:
        raise _native_error()


def _terminate_job(job: _Job) -> None:
    win32job.TerminateJobObject(job.handle, _TERMINATED_EXIT_CODE)


def _process_exited(process: int) -> bool:
    status = _KERNEL.WaitForSingleObject(process, 0)
    if status not in (_WAIT_OBJECT_0, _WAIT_TIMEOUT):
        raise _native_error()
    return status == _WAIT_OBJECT_0


def _active_processes(job: _Job) -> int:
    return win32job.QueryInformationJobObject(
        job.handle, win32job.JobObjectBasicAccountingInformation
    )["ActiveProcesses"]


def _read_pipe(handle: int) -> bytes | None:
    # These handles have exactly one reader and no concurrent I/O. Once Peek reports
    # available bytes no other reader can consume them before this bounded ReadFile.
    available = wintypes.DWORD()
    if not _KERNEL.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
        if ctypes.get_last_error() in _PIPE_EOF_ERRORS:
            return None
        raise _native_error()
    if not available.value:
        return b""
    size = min(available.value, _READ_CHUNK_BYTES)
    buffer = ctypes.create_string_buffer(size)
    read = wintypes.DWORD()
    if not _KERNEL.ReadFile(handle, buffer, size, ctypes.byref(read), None):
        if ctypes.get_last_error() in _PIPE_EOF_ERRORS:
            return None
        raise _native_error()
    return buffer.raw[: read.value]


def _capture_until_exit(resources: _Resources, deadline: float) -> int:
    while True:
        progress = False
        for pipe in resources.pipes:
            progress |= pipe.pump()
        if (
            _process_exited(resources.process.value)
            and _active_processes(resources.job) == 0
            and all(pipe.eof for pipe in resources.pipes)
        ):
            code = wintypes.DWORD()
            if not _KERNEL.GetExitCodeProcess(resources.process.value, ctypes.byref(code)):
                raise _native_error()
            return code.value
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _DeadlineExpired()
        if not progress:
            time.sleep(min(_POLL_SECONDS, remaining))


def _finish(resources: _Resources, *, terminate: bool, timeout: float) -> bool:
    """Bound cleanup, fail visibly on uncertainty, and close handles even on interruption."""
    ok = True
    deadline = time.monotonic() + timeout
    try:
        for handle in resources.child_handles:
            try:
                handle.close()
            except Exception:
                ok = False
        if terminate and resources.process is not None:
            try:
                if resources.assigned:
                    _terminate_job(resources.job)
                elif not _process_exited(resources.process.value):
                    if not _KERNEL.TerminateProcess(resources.process.value, _TERMINATED_EXIT_CODE):
                        raise _native_error()
            except Exception:
                ok = False
                # Closing the sole containment handle is a safety fallback, not
                # evidence that termination/drain succeeded without uncertainty.
                if resources.job is not None:
                    try:
                        resources.job.close()
                    except Exception:
                        pass
                try:
                    if not _process_exited(resources.process.value):
                        _KERNEL.TerminateProcess(resources.process.value, _TERMINATED_EXIT_CODE)
                except Exception:
                    pass
            while True:
                try:
                    for pipe in resources.pipes:
                        pipe.pump()
                    exited = _process_exited(resources.process.value)
                    job_empty = (
                        resources.job is None
                        or resources.job.handle is None
                        or _active_processes(resources.job) == 0
                    )
                    if exited and job_empty and all(pipe.eof for pipe in resources.pipes):
                        break
                except Exception:
                    ok = False
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    ok = False
                    break
                time.sleep(min(_POLL_SECONDS, remaining))
    except BaseException:
        # In particular, an interrupt during terminate/drain must not bypass the
        # KILL_ON_JOB_CLOSE fallback or retain the process/pipe handles below.
        ok = False
    finally:
        # An unassigned primary thread is still suspended and has no descendants.
        # It needs its own termination fallback; closing an empty Job cannot kill it.
        if terminate and resources.process is not None and not resources.assigned:
            try:
                if not _process_exited(resources.process.value):
                    if not _KERNEL.TerminateProcess(resources.process.value, _TERMINATED_EXIT_CODE):
                        raise _native_error()
            except BaseException:
                ok = False
        if resources.job is not None:
            try:
                resources.job.close()
            except BaseException:
                ok = False
        if terminate and resources.process is not None:
            try:
                milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
                if (
                    _KERNEL.WaitForSingleObject(resources.process.value, milliseconds)
                    != _WAIT_OBJECT_0
                ):
                    ok = False
            except BaseException:
                ok = False
        for handle in reversed(resources.handles):
            try:
                handle.close()
            except BaseException:
                ok = False
    return ok


__all__ = ["WindowsProcessError", "WindowsProcessResult", "run_windows_process"]
