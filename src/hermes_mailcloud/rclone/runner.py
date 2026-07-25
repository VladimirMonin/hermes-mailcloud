"""Safe rclone subprocess boundary and stable failure classification."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import IO

from ..core.errors import ErrorKind, ErrorPayload, MailCloudError

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_CAPTURE_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_CLEANUP_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class RcloneResult:
    """Bounded raw backend output kept in memory until a parser consumes it."""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class RcloneRunnerError(MailCloudError):
    """Typed startup or timeout failure from the safe process boundary."""


class RcloneRunner:
    """Invoke an argv-only rclone process without printing or inheriting secrets."""

    def __init__(
        self,
        binary: str | Sequence[str] = "rclone",
        *,
        environment: Mapping[str, str] | None = None,
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        self._binary = _validate_argv_prefix(binary)
        if (
            isinstance(max_capture_bytes, bool)
            or not isinstance(max_capture_bytes, int)
            or max_capture_bytes < 1
        ):
            raise ValueError("max_capture_bytes must be a positive integer")
        self._environment = deterministic_environment(environment)
        self._max_capture_bytes = max_capture_bytes

    def run(self, args: Sequence[str], *, timeout_seconds: float | None = None) -> RcloneResult:
        """Execute literal rclone argv with bounded concurrent stream capture."""
        command = (*self._binary, *_validate_args(args))
        timeout = _validated_timeout(timeout_seconds)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._environment,
                shell=False,
                start_new_session=os.name == "posix",
                text=False,
            )
        except FileNotFoundError as exc:
            raise RcloneRunnerError(
                ErrorPayload(ErrorKind.RCLONE_NOT_FOUND, "rclone executable was not found")
            ) from exc
        except OSError as exc:
            raise RcloneRunnerError(
                ErrorPayload(ErrorKind.UNKNOWN_ERROR, "rclone process could not be started")
            ) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_capture = _BoundedCapture(self._max_capture_bytes)
        stderr_capture = _BoundedCapture(self._max_capture_bytes)
        readers = (
            _start_reader(process.stdout, stdout_capture),
            _start_reader(process.stderr, stderr_capture),
        )
        deadline = started + timeout
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            timeout_error = exc
        else:
            timeout_error = None
            remaining = max(0.0, deadline - time.monotonic())
            if not _join_readers(readers, timeout_seconds=remaining):
                timeout_error = subprocess.TimeoutExpired(command, timeout)

        if timeout_error is not None:
            _kill_process_tree(process)
            if process.poll() is None:
                process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            _join_readers(readers, timeout_seconds=_CLEANUP_TIMEOUT_SECONDS)
            raise RcloneRunnerError(
                ErrorPayload(
                    ErrorKind.TIMEOUT,
                    "rclone command timed out",
                    {"timeout_seconds": timeout},
                )
            ) from timeout_error

        duration_ms = int((time.monotonic() - started) * 1000)
        return RcloneResult(
            returncode=process.returncode,
            stdout=stdout_capture.text,
            stderr=stderr_capture.text,
            duration_ms=duration_ms,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
        )

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        """Run a command and turn every nonzero backend result into a typed error."""
        result = self.run(args, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            raise RcloneRunnerError(map_rclone_error(result))
        return result


def deterministic_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the narrow environment rclone needs without inheriting unrelated secrets."""
    inherited = os.environ if source is None else source
    environment = {
        "PATH": inherited.get("PATH") or os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    for key in ("HOME", "XDG_CONFIG_HOME", "RCLONE_CONFIG"):
        value = inherited.get(key)
        if value:
            environment[key] = value
    return environment


def map_rclone_error(result: RcloneResult) -> ErrorPayload:
    """Classify a nonzero result without allowing backend text into public payloads."""
    if result.returncode == 0:
        raise ValueError("only nonzero rclone results can be mapped to an error")

    output = f"{result.stderr}\n{result.stdout}".casefold()
    if _contains_any(
        output,
        (
            "didn't find section in config file",
            "remote not found",
            "unknown remote",
            "no remotes found",
        ),
    ):
        kind = ErrorKind.REMOTE_NOT_CONFIGURED
        message = "configured rclone remote is unavailable"
    elif _contains_any(
        output, ("access denied", "permission denied", "unauthorized", "authentication")
    ):
        kind = ErrorKind.ACCESS_DENIED
        message = "rclone access was denied"
    elif _contains_any(output, ("already exists", "directory not empty", "file exists")):
        kind = ErrorKind.CONFLICT
        message = "rclone reported a conflicting remote object"
    elif _contains_any(
        output,
        (
            "network is unreachable",
            "network unreachable",
            "connection refused",
            "no such host",
            "temporary failure",
            "i/o timeout",
            "dial tcp",
            "context deadline exceeded",
            "tls handshake timeout",
        ),
    ):
        kind = ErrorKind.NETWORK_ERROR
        message = "rclone network request failed"
    elif _contains_any(output, ("not supported", "unsupported")):
        kind = ErrorKind.BACKEND_UNSUPPORTED
        message = "rclone backend does not support this operation"
    elif _contains_any(output, ("not found", "does not exist", "object not found")):
        kind = ErrorKind.NOT_FOUND
        message = "rclone remote object was not found"
    else:
        kind = ErrorKind.UNKNOWN_ERROR
        message = "rclone command failed"

    return ErrorPayload(kind, message, {"backend_exit_code": result.returncode})


def _validate_argv_prefix(binary: str | Sequence[str]) -> tuple[str, ...]:
    values = (binary,) if isinstance(binary, str) else tuple(binary)
    if not values or any(
        not isinstance(value, str) or not value or "\x00" in value for value in values
    ):
        raise ValueError("rclone binary must be a non-empty argv prefix without NUL")
    return values


def _validate_args(args: Sequence[str]) -> tuple[str, ...]:
    values = tuple(args)
    if any(not isinstance(value, str) or "\x00" in value for value in values):
        raise ValueError("rclone arguments must be strings without NUL")
    return values


def _validated_timeout(value: float | None) -> float:
    timeout = DEFAULT_TIMEOUT_SECONDS if value is None else value
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout_seconds must be a positive number")
    return float(timeout)


def _contains_any(value: str, markers: Sequence[str]) -> bool:
    return any(marker in value for marker in markers)


@dataclass(slots=True)
class _BoundedCapture:
    limit: int
    buffer: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        remaining = self.limit - len(self.buffer)
        if remaining > 0:
            self.buffer.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True

    @property
    def text(self) -> str:
        return bytes(self.buffer).decode("utf-8", errors="replace")


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the isolated POSIX process group so descendants cannot retain pipes."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    try:
        process.kill()
    except ProcessLookupError:
        pass


def _start_reader(stream: IO[bytes], capture: _BoundedCapture) -> threading.Thread:
    thread = threading.Thread(target=_read_bounded, args=(stream, capture), daemon=True)
    thread.start()
    return thread


def _read_bounded(stream: IO[bytes], capture: _BoundedCapture) -> None:
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            capture.append(chunk)
    finally:
        stream.close()


def _join_readers(
    readers: Sequence[threading.Thread], *, timeout_seconds: float | None = None
) -> bool:
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    for reader in readers:
        timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
        reader.join(timeout)
    return all(not reader.is_alive() for reader in readers)
