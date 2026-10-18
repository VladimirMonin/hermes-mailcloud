"""Real native tests for the private Windows Job/process adapter, without rclone/cloud."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

import pytest

if os.name != "nt":
    pytest.skip("native Windows process adapter", allow_module_level=True)

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32event  # noqa: E402
import win32job  # noqa: E402
import win32process  # noqa: E402

from hermes_mailcloud.core.errors import ErrorKind  # noqa: E402
from hermes_mailcloud.rclone import _windows_process as native  # noqa: E402
from hermes_mailcloud.rclone.runner import (  # noqa: E402
    RcloneRunner,
    RcloneRunnerError,
    deterministic_environment,
)

ROOT = Path(__file__).resolve().parents[2]
_KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
_GET_HANDLE_INFORMATION = _KERNEL.GetHandleInformation
_GET_HANDLE_INFORMATION.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_GET_HANDLE_INFORMATION.restype = wintypes.BOOL
_GET_PROCESS_HANDLE_COUNT = _KERNEL.GetProcessHandleCount
_GET_PROCESS_HANDLE_COUNT.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_GET_PROCESS_HANDLE_COUNT.restype = wintypes.BOOL
_GET_PROCESS_ID = _KERNEL.GetProcessId
_GET_PROCESS_ID.argtypes = [wintypes.HANDLE]
_GET_PROCESS_ID.restype = wintypes.DWORD


_GRANDCHILD = """
import json
import os
import sys
import time
from pathlib import Path
ready, nonce = sys.argv[1:]
print("descendant-stdout-ready", flush=True)
print("descendant-stderr-ready", file=sys.stderr, flush=True)
payload = {"pid": os.getpid(), "nonce": nonce, "role": "descendant"}
temporary = Path(ready + ".tmp")
temporary.write_text(json.dumps(payload), encoding="utf-8")
os.replace(temporary, ready)
time.sleep(60)
"""

_PARENT = """
import json
import os
import subprocess
import sys
import time
from pathlib import Path
script, child_ready, parent_ready, release, nonce, mode = sys.argv[1:]
child = subprocess.Popen(
    [sys.executable, script, child_ready, nonce],
    stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr, close_fds=True,
)
deadline = time.monotonic() + 8
while not Path(child_ready).exists():
    if child.poll() is not None or time.monotonic() >= deadline:
        raise SystemExit(91)
    time.sleep(0.005)
payload = {"pid": os.getpid(), "nonce": nonce, "role": "parent"}
temporary = Path(parent_ready + ".tmp")
temporary.write_text(json.dumps(payload), encoding="utf-8")
os.replace(temporary, parent_ready)
while not Path(release).exists():
    if time.monotonic() >= deadline:
        raise SystemExit(92)
    time.sleep(0.005)
if mode == "exit-parent":
    raise SystemExit(0)
if mode == "finish-all":
    child.terminate()
    child.wait(timeout=3)
    print("parent-finished", flush=True)
    raise SystemExit(0)
time.sleep(60)
"""


def _environment(root: Path, *, source_import: bool = False) -> dict[str, str]:
    for name in ("home", "config", "empty-path"):
        (root / name).mkdir(parents=True, exist_ok=True)
    source = {
        "PATH": str(root / "empty-path"),
        "SystemRoot": os.environ["SystemRoot"],
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "RCLONE_CONFIG": str(root / "synthetic-rclone.conf"),
        "RCLONE_PASSWORD": "must-not-inherit-rclone-sentinel",
        "HMC_TOKEN": "must-not-inherit-hmc-sentinel",
    }
    environment = deterministic_environment(source)
    if source_import:
        environment["PYTHONPATH"] = str(ROOT / "src")
    return environment


def _run(root: Path, code: str, *arguments: str, **overrides: object):
    options = {
        "environment": _environment(root),
        "timeout_seconds": 4.0,
        "max_capture_bytes": 1024 * 1024,
        **overrides,
    }
    return native.run_windows_process(
        [sys.executable, "-c", textwrap.dedent(code), *arguments], **options
    )


def _handle_flags(handle: int) -> int:
    flags = wintypes.DWORD()
    assert _GET_HANDLE_INFORMATION(handle, ctypes.byref(flags))
    return flags.value


def _handle_count() -> int:
    count = wintypes.DWORD()
    assert _GET_PROCESS_HANDLE_COUNT(int(win32api.GetCurrentProcess()), ctypes.byref(count))
    return count.value


def _duplicate(handle: int):
    current = win32api.GetCurrentProcess()
    return win32api.DuplicateHandle(
        current, handle, current, 0, False, win32con.DUPLICATE_SAME_ACCESS
    )


@dataclass
class _Identity:
    handle: object
    pid: int
    creation_time: object

    def exited(self, timeout_ms: int = 0) -> bool:
        return win32event.WaitForSingleObject(self.handle, timeout_ms) == win32event.WAIT_OBJECT_0

    def close(self) -> None:
        self.handle.Close()


def _ready_identity(path: Path, nonce: str, role: str, *, timeout: float = 3) -> _Identity:
    """Obtain an own marker within one budget; never retry identity mismatches."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"own {role} readiness payload was not obtained before the deadline"
            ) from last_error
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (
            FileNotFoundError,
            PermissionError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            # Only publication/read availability is retried, not arbitrary I/O or
            # process errors. A persistent refusal or partial payload still fails.
            last_error = exc
        else:
            last_error = None
            assert isinstance(payload, dict), f"invalid own {role} readiness payload"
            assert payload.get("nonce") == nonce, f"wrong own {role} readiness nonce"
            assert payload.get("role") == role, f"wrong own {role} readiness role"
            assert type(payload.get("pid")) is int and payload["pid"] > 0, (
                f"invalid own {role} readiness pid"
            )
            if time.monotonic() < deadline:
                break
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.005, remaining))
    handle = win32api.OpenProcess(
        win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE | 0x1000, False, payload["pid"]
    )
    assert _GET_PROCESS_ID(int(handle)) == payload["pid"]
    creation = win32process.GetProcessTimes(handle)["CreationTime"]
    return _Identity(handle, payload["pid"], creation)


def _tree_files(root: Path, mode: str):
    root.mkdir(parents=True, exist_ok=True)
    descendant = root / "descendant ü.py"
    parent = root / "parent & literal.py"
    descendant.write_text(textwrap.dedent(_GRANDCHILD), encoding="utf-8")
    parent.write_text(textwrap.dedent(_PARENT), encoding="utf-8")
    nonce = uuid.uuid4().hex
    child_ready = root / "descendant-ready.json"
    parent_ready = root / "parent-ready.json"
    release = root / "release-parent"
    argv = [
        sys.executable,
        str(parent),
        str(descendant),
        str(child_ready),
        str(parent_ready),
        str(release),
        nonce,
        mode,
    ]
    return argv, nonce, child_ready, parent_ready, release


@dataclass
class _TreeRun:
    root: Path
    mode: str
    timeout: float = 4.0
    through_runner: bool = False
    outcomes: list[object] = field(default_factory=list)
    identities: list[_Identity] = field(default_factory=list)
    thread: threading.Thread | None = None
    release: Path | None = None

    def start(self) -> None:
        argv, nonce, child_ready, parent_ready, self.release = _tree_files(self.root, self.mode)

        def supervise() -> None:
            try:
                if self.through_runner:
                    result = RcloneRunner(
                        argv,
                        environment=_environment(self.root),
                        max_capture_bytes=128,
                    ).run([], timeout_seconds=self.timeout)
                else:
                    result = native.run_windows_process(
                        argv,
                        environment=_environment(self.root),
                        timeout_seconds=self.timeout,
                        max_capture_bytes=128,
                        cleanup_timeout_seconds=1.5,
                    )
                self.outcomes.append(result)
            except BaseException as exc:
                self.outcomes.append(exc)

        self.thread = threading.Thread(target=supervise, name="test-native-supervisor", daemon=True)
        self.thread.start()
        self.identities.append(_ready_identity(child_ready, nonce, "descendant"))
        self.identities.append(_ready_identity(parent_ready, nonce, "parent"))
        assert not any(identity.exited() for identity in self.identities)

    @property
    def descendant(self) -> _Identity:
        return self.identities[0]

    @property
    def parent(self) -> _Identity:
        return self.identities[1]

    def wait(self) -> object:
        self.thread.join(timeout=self.timeout + 3)
        assert not self.thread.is_alive(), "adapter supervisor did not finish within its budget"
        assert len(self.outcomes) == 1
        return self.outcomes[0]

    def close(self) -> None:
        if self.release is not None:
            self.release.touch()
        if self.thread is not None:
            self.thread.join(timeout=self.timeout + 3)
        for identity in self.identities:
            if not identity.exited():
                # Test emergency cleanup is limited to the exact self-ready handles.
                win32api.TerminateProcess(identity.handle, 97)
                identity.exited(2000)
        if self.thread is not None:
            self.thread.join(timeout=2)
        for identity in self.identities:
            identity.close()


@contextmanager
def _tree(
    root: Path,
    mode: str = "hold",
    *,
    through_runner: bool = False,
) -> Iterator[_TreeRun]:
    exercise = _TreeRun(root, mode, through_runner=through_runner)
    try:
        exercise.start()
        yield exercise
    finally:
        exercise.close()


@dataclass
class _ReadinessClock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert 0 < seconds <= 0.005
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def unready_observer(monkeypatch: pytest.MonkeyPatch) -> _ReadinessClock:
    clock = _ReadinessClock()
    # Replace only this test module's binding, not the shared time module or the
    # production adapter's clock. Negative controls never launch a process.
    monkeypatch.setattr(sys.modules[__name__], "time", clock)

    def forbidden_open(*_args, **_kwargs):
        pytest.fail("unvalidated readiness must not open a process")

    monkeypatch.setattr(win32api, "OpenProcess", forbidden_open)
    return clock


@pytest.mark.parametrize("role", ["parent", "descendant"])
@pytest.mark.parametrize("publication", ["refused", "missing", "partial-json"])
def test_ready_identity_retries_publication_reads_before_accepting_real_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    publication: str,
) -> None:
    marker = tmp_path / f"{role}-ready.json"
    real_read = Path.read_text
    injected = 0
    successful_reads = 0

    def read_marker(path, *args, **kwargs):
        nonlocal injected, successful_reads
        # Schedule the two synthetic failures only after real self-publication;
        # polling before publication must not consume the injected-fault control.
        if path == marker and path.exists() and injected < 2:
            injected += 1
            if publication == "refused":
                raise PermissionError(13, "synthetic marker read refusal")
            if publication == "missing":
                raise FileNotFoundError(2, "synthetic marker not yet readable")
            return '{"pid":'
        text = real_read(path, *args, **kwargs)
        if path == marker:
            successful_reads += 1
        return text

    monkeypatch.setattr(Path, "read_text", read_marker)
    with _tree(tmp_path, "finish-all") as exercise:
        assert injected == 2
        assert successful_reads == 1
        payload = json.loads(real_read(marker, encoding="utf-8"))
        identity = exercise.parent if role == "parent" else exercise.descendant
        assert payload["role"] == role
        assert payload["pid"] == identity.pid == _GET_PROCESS_ID(int(identity.handle))
        assert (
            identity.creation_time == win32process.GetProcessTimes(identity.handle)["CreationTime"]
        )
        assert not identity.exited()
        exercise.release.touch()
        result = exercise.wait()
        assert isinstance(result, native.WindowsProcessResult)
        assert result.returncode == 0
    assert not exercise.thread.is_alive()


@pytest.mark.parametrize(
    "publication", ["refused", "missing", "partial-json", "partial-utf8", "slow-refused"]
)
def test_ready_identity_persistent_read_failures_exhaust_only_one_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unready_observer: _ReadinessClock,
    publication: str,
) -> None:
    marker = tmp_path / "unavailable-ready.json"
    marker.touch()
    clock = unready_observer
    budget = 0.02
    read_cost = 0.003 if publication == "slow-refused" else 0
    attempts: list[float] = []
    real_read = Path.read_text

    def read_marker(path, *args, **kwargs):
        if path != marker:
            return real_read(path, *args, **kwargs)
        attempts.append(clock.now)
        clock.now += read_cost
        if publication in {"refused", "slow-refused"}:
            raise PermissionError(13, "synthetic persistent marker refusal")
        if publication == "missing":
            raise FileNotFoundError(2, "synthetic missing marker")
        if publication == "partial-utf8":
            raise UnicodeDecodeError("utf-8", b"\xc3", 0, 1, "synthetic partial publication")
        return '{"nonce":'

    monkeypatch.setattr(Path, "read_text", read_marker)
    with pytest.raises(AssertionError, match="readiness") as caught:
        _ready_identity(marker, "own-nonce", "parent", timeout=budget)
    expected = {
        "refused": PermissionError,
        "slow-refused": PermissionError,
        "missing": FileNotFoundError,
        "partial-json": json.JSONDecodeError,
        "partial-utf8": UnicodeDecodeError,
    }[publication]
    assert isinstance(caught.value.__cause__, expected)
    assert len(attempts) == (3 if read_cost else 4)
    assert all(start < budget for start in attempts)
    assert clock.now == pytest.approx(budget)
    assert sum(clock.sleeps) + read_cost * len(attempts) == pytest.approx(budget)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"nonce": "other", "role": "parent", "pid": 12345},
        {"nonce": "own-nonce", "role": "descendant", "pid": 12345},
        {"nonce": "own-nonce", "role": "parent", "pid": 0},
        {"nonce": "own-nonce", "role": "parent", "pid": True},
        {"nonce": "own-nonce", "role": "parent", "pid": "12345"},
    ],
)
def test_ready_identity_rejects_invalid_payload_before_opening_process(
    tmp_path: Path,
    unready_observer: _ReadinessClock,
    payload,
) -> None:
    marker = tmp_path / "invalid-ready.json"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AssertionError):
        _ready_identity(marker, "own-nonce", "parent", timeout=0.02)
    assert unready_observer.now == 0
    assert unready_observer.sleeps == []


def test_ready_identity_does_not_accept_a_payload_obtained_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unready_observer: _ReadinessClock,
) -> None:
    marker = tmp_path / "late-ready.json"
    marker.touch()
    clock = unready_observer
    real_read = Path.read_text

    def late_read(path, *args, **kwargs):
        if path == marker:
            clock.now = 0.021
            return json.dumps({"nonce": "own-nonce", "role": "parent", "pid": 12345})
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", late_read)
    with pytest.raises(AssertionError, match="readiness"):
        _ready_identity(marker, "own-nonce", "parent", timeout=0.02)
    assert clock.sleeps == []


@pytest.mark.parametrize("failure", [OSError, RuntimeError])
def test_ready_identity_does_not_retry_unrelated_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unready_observer: _ReadinessClock,
    failure,
) -> None:
    marker = tmp_path / "unrelated-error-ready.json"
    marker.touch()
    attempts = 0
    real_read = Path.read_text

    def read_marker(path, *args, **kwargs):
        nonlocal attempts
        if path == marker:
            attempts += 1
            raise failure("synthetic unrelated observer error")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_marker)
    with pytest.raises(failure, match="unrelated observer error"):
        _ready_identity(marker, "own-nonce", "parent", timeout=0.02)
    assert attempts == 1
    assert unready_observer.now == 0
    assert unready_observer.sleeps == []


def test_literal_argv_exact_environment_and_stdin_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HMC_TOKEN", "forbidden-host-sentinel")
    monkeypatch.setenv("RCLONE_PASSWORD", "forbidden-host-sentinel")
    environment = _environment(tmp_path)
    arguments = ["space value", "отчёт ü", "&;|$%NOT_EXPANDED%", 'a"b', "", "C:\\a b\\"]
    code = """
        import json, os, sys
        print(json.dumps({"argv": sys.argv[1:], "environment": dict(os.environ),
                          "stdin": sys.stdin.read()}, ensure_ascii=True))
    """
    result = _run(tmp_path, code, *arguments, environment=environment)
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["argv"] == arguments
    assert payload["stdin"] == ""
    assert {key.upper(): value for key, value in payload["environment"].items()} == {
        key.upper(): value for key, value in environment.items()
    }
    assert "forbidden-host-sentinel" not in result.stdout
    assert not result.stdout_truncated and not result.stderr_truncated


def test_both_streams_are_drained_and_capture_is_bounded(tmp_path: Path) -> None:
    code = """
        import sys
        sys.stdout.buffer.write(b"o" * 300000)
        sys.stderr.buffer.write(b"e" * 300000)
        raise SystemExit(7)
    """
    result = _run(tmp_path, code, max_capture_bytes=31)
    assert result.returncode == 7
    assert result.stdout == "o" * 31
    assert result.stderr == "e" * 31
    assert result.stdout_truncated and result.stderr_truncated


def test_capture_decodes_untrusted_utf8_without_raising(tmp_path: Path) -> None:
    result = _run(tmp_path, "import sys; sys.stdout.buffer.write(bytes([255, 254]))")
    assert result.stdout == "\ufffd\ufffd"
    assert result.returncode == 0


def test_missing_executable_is_typed_and_never_echoes_private_argv(tmp_path: Path) -> None:
    def missing():
        return native.run_windows_process(
            [str(tmp_path / "private-path-sentinel.exe"), "raw-capability-sentinel"],
            environment=_environment(tmp_path),
            timeout_seconds=1,
            max_capture_bytes=32,
        )

    with pytest.raises(native.WindowsProcessError) as caught:
        missing()
    assert caught.value.error.kind is ErrorKind.RCLONE_NOT_FOUND
    assert "sentinel" not in json.dumps(caught.value.error.to_payload())
    assert caught.value.__cause__ is None
    # A first failed native launch has a one-time handle-count delta on this host.
    # Measure repeated-failure growth; startup-fault tests also assert owned closes.
    before = _handle_count()
    for _ in range(3):
        with pytest.raises(native.WindowsProcessError):
            missing()
    assert _handle_count() == before


@pytest.mark.parametrize("command", [[], "a.exe", ["relative.exe"], [r"C:\x.cmd"], ["bad\x00.exe"]])
def test_adapter_rejects_nonliteral_or_unresolved_executables(tmp_path: Path, command) -> None:
    with pytest.raises(ValueError):
        native.run_windows_process(
            command,
            environment=_environment(tmp_path),
            timeout_seconds=1,
            max_capture_bytes=32,
        )


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_invalid_deadlines_are_rejected_before_native_create(tmp_path: Path, timeout) -> None:
    with pytest.raises(ValueError):
        _run(tmp_path, "raise SystemExit(0)", timeout_seconds=timeout)


@pytest.mark.parametrize("environment", [{"PATH": "x", "path": "y"}, {"A=B": "x"}, {"A": "x\x00"}])
def test_invalid_environment_is_rejected(tmp_path: Path, environment) -> None:
    with pytest.raises(ValueError):
        _run(tmp_path, "raise SystemExit(0)", environment=environment)


def test_suspended_create_assign_then_resume_before_any_child_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "first-child-effect"
    events: list[str] = []
    duplicates: list[object] = []
    jobs: list[object] = []
    real_create = native._create_process
    real_job = native._create_job
    real_assign = native._assign_job
    real_resume = native._resume_thread

    def create_job():
        job = real_job()
        jobs.append(job)
        assert _handle_flags(int(job.handle)) & 1 == 0
        flags = win32job.QueryInformationJobObject(
            job.handle, win32job.JobObjectExtendedLimitInformation
        )["BasicLimitInformation"]["LimitFlags"]
        assert flags & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        assert not flags & (
            win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK | win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
        )
        return job

    def create(*args, **kwargs):
        process = real_create(*args, **kwargs)
        duplicates.append(_duplicate(process.process_handle))
        assert _handle_flags(process.process_handle) & 1 == 0
        assert _handle_flags(process.thread_handle) & 1 == 0
        time.sleep(0.05)
        assert not marker.exists()
        events.append("create-suspended")
        return process

    def assign(job, process):
        assert events == ["create-suspended"]
        assert not marker.exists()
        real_assign(job, process)
        assert win32job.IsProcessInJob(process, job.handle)
        events.append("assigned")

    def resume(thread):
        assert events == ["create-suspended", "assigned"]
        assert not marker.exists()
        events.append("resume")
        real_resume(thread)

    monkeypatch.setattr(native, "_create_job", create_job)
    monkeypatch.setattr(native, "_create_process", create)
    monkeypatch.setattr(native, "_assign_job", assign)
    monkeypatch.setattr(native, "_resume_thread", resume)
    try:
        result = _run(
            tmp_path, "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", str(marker)
        )
        assert result.returncode == 0
        assert marker.exists()
        assert events == ["create-suspended", "assigned", "resume"]
        assert win32event.WaitForSingleObject(duplicates[0], 1000) == win32event.WAIT_OBJECT_0
        assert jobs[0].handle is None
    finally:
        for handle in duplicates:
            handle.Close()


def test_explicit_handle_list_does_not_inherit_an_unrelated_inheritable_event(
    tmp_path: Path,
) -> None:
    # CreateEvent defaults non-inheritable; explicitly make only this test event inheritable.
    event = win32event.CreateEvent(None, True, False, None)
    native._set_inheritable(int(event), True)
    try:
        code = """
            import json, sys, win32event
            try:
                win32event.SetEvent(int(sys.argv[1]))
                print(json.dumps({"inherited": True}))
            except Exception:
                print(json.dumps({"inherited": False}))
        """
        result = _run(tmp_path, code, str(int(event)))
        assert result.returncode == 0
        assert json.loads(result.stdout) == {"inherited": False}
        assert win32event.WaitForSingleObject(event, 0) == win32event.WAIT_TIMEOUT
    finally:
        event.Close()


@pytest.mark.parametrize("through_runner", [False, True])
def test_timeout_waits_for_real_descendant_readiness_and_kills_the_exact_tree(
    tmp_path: Path,
    through_runner: bool,
) -> None:
    before_threads = {thread.ident for thread in threading.enumerate()}
    with _tree(tmp_path, through_runner=through_runner) as exercise:
        exercise.release.touch()
        outcome = exercise.wait()
        assert isinstance(outcome, (native.WindowsProcessError, RcloneRunnerError))
        assert outcome.error.kind is ErrorKind.TIMEOUT
        assert outcome.error.exit_code == 14
        assert outcome.error.details == {"timeout_seconds": 4.0}
        assert exercise.parent.exited(1500)
        assert exercise.descendant.exited(1500)
        assert exercise.parent.creation_time and exercise.descendant.creation_time
    assert {thread.ident for thread in threading.enumerate()} == before_threads


@pytest.mark.parametrize("through_runner", [False, True])
def test_parent_exit_does_not_make_descendant_held_pipes_a_false_success(
    tmp_path: Path,
    through_runner: bool,
) -> None:
    with _tree(tmp_path, "exit-parent", through_runner=through_runner) as exercise:
        exercise.release.touch()
        assert exercise.parent.exited(1500)
        assert not exercise.descendant.exited()
        assert exercise.thread.is_alive(), "held stdout/stderr were not observed"
        outcome = exercise.wait()
        assert isinstance(outcome, (native.WindowsProcessError, RcloneRunnerError))
        assert outcome.error.kind is ErrorKind.TIMEOUT
        assert exercise.descendant.exited(1500)


def test_normal_exit_drains_descendant_output_and_closes_all_handles(tmp_path: Path) -> None:
    before = _handle_count()
    with _tree(tmp_path, "finish-all") as exercise:
        exercise.release.touch()
        outcome = exercise.wait()
        assert isinstance(outcome, native.WindowsProcessResult)
        assert outcome.returncode == 0
        assert "descendant-stdout-ready" in outcome.stdout
        assert "descendant-stderr-ready" in outcome.stderr
        assert "parent-finished" in outcome.stdout
        assert exercise.parent.exited(1000) and exercise.descendant.exited(1000)
    assert _handle_count() <= before + 1


@pytest.mark.parametrize("stage", ["job", "attributes", "create", "assign", "resume"])
def test_startup_faults_never_resume_child_effects_and_release_own_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    marker = tmp_path / "must-not-run"
    before = _handle_count()
    owned: list[object] = []
    duplicates: list[object] = []
    real_own = native._Resources.own
    real_create = native._create_process

    def observe_own(resources, value):
        handle = real_own(resources, value)
        owned.append(handle)
        return handle

    def observe_create(*args, **kwargs):
        process = real_create(*args, **kwargs)
        duplicates.append(_duplicate(process.process_handle))
        return process

    def fail(*_args, **_kwargs):
        raise OSError("private-startup-fault-sentinel")

    monkeypatch.setattr(native._Resources, "own", observe_own)
    monkeypatch.setattr(native, "_create_process", observe_create)
    if stage == "job":
        monkeypatch.setattr(native.win32job, "SetInformationJobObject", fail)
    elif stage == "attributes":
        monkeypatch.setattr(native._KERNEL, "UpdateProcThreadAttribute", fail)
    elif stage == "create":
        monkeypatch.setattr(native._KERNEL, "CreateProcessW", fail)
    elif stage == "assign":
        monkeypatch.setattr(native, "_assign_job", fail)
    else:
        monkeypatch.setattr(native, "_resume_thread", fail)
    try:
        with pytest.raises(native.WindowsProcessError) as caught:
            _run(
                tmp_path,
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            )
        assert caught.value.error.kind is ErrorKind.UNKNOWN_ERROR
        assert "sentinel" not in str(caught.value)
        assert not marker.exists()
        assert all(handle.value is None for handle in owned)
        assert all(
            win32event.WaitForSingleObject(handle, 1500) == win32event.WAIT_OBJECT_0
            for handle in duplicates
        )
    finally:
        for handle in duplicates:
            handle.Close()
    assert _handle_count() <= before + 1


def test_unassigned_suspended_child_cleanup_survives_an_interrupted_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "must-not-resume"
    duplicates: list[object] = []
    calls: list[int] = []
    real_create = native._create_process
    real_terminate = native._KERNEL.TerminateProcess

    def observe_create(*args, **kwargs):
        process = real_create(*args, **kwargs)
        duplicates.append(_duplicate(process.process_handle))
        return process

    def refuse_assignment(*_args):
        raise OSError("private-assign-fault")

    def interrupt_first_termination(process, code):
        calls.append(process)
        if len(calls) == 1:
            raise KeyboardInterrupt("private-cleanup-interrupt")
        return real_terminate(process, code)

    monkeypatch.setattr(native, "_create_process", observe_create)
    monkeypatch.setattr(native, "_assign_job", refuse_assignment)
    monkeypatch.setattr(native._KERNEL, "TerminateProcess", interrupt_first_termination)
    try:
        with pytest.raises(native.WindowsProcessError) as caught:
            _run(
                tmp_path,
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            )
        assert caught.value.error.kind is ErrorKind.UNKNOWN_ERROR
        assert len(calls) == 2
        assert not marker.exists()
        assert duplicates
        assert all(
            win32event.WaitForSingleObject(handle, 1000) == win32event.WAIT_OBJECT_0
            for handle in duplicates
        )
    finally:
        for handle in duplicates:
            handle.Close()


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize("when", ["before", "after"])
def test_cleanup_fault_is_not_reported_as_a_clean_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure,
    when: str,
) -> None:
    real_terminate = native._terminate_job
    real_own = native._Resources.own
    real_job = native._create_job
    owned: list[object] = []
    jobs: list[object] = []

    def observe_own(resources, value):
        handle = real_own(resources, value)
        owned.append(handle)
        return handle

    def observe_job():
        job = real_job()
        jobs.append(job)
        return job

    def terminate_then_fail(job):
        if when == "after":
            real_terminate(job)
        raise failure("private-cleanup-fault-sentinel")

    monkeypatch.setattr(native, "_terminate_job", terminate_then_fail)
    monkeypatch.setattr(native._Resources, "own", observe_own)
    monkeypatch.setattr(native, "_create_job", observe_job)
    with _tree(tmp_path) as exercise:
        exercise.release.touch()
        outcome = exercise.wait()
        assert isinstance(outcome, native.WindowsProcessError)
        assert outcome.error.kind is ErrorKind.UNKNOWN_ERROR
        assert "cleanup could not be confirmed" in str(outcome)
        assert "sentinel" not in str(outcome)
        assert exercise.parent.exited(1500) and exercise.descendant.exited(1500)
    assert owned and all(handle.value is None for handle in owned)
    assert jobs and all(job.handle is None for job in jobs)


@pytest.mark.parametrize("marker_refusals", [0, 2], ids=["plain-marker", "refused-marker"])
def test_native_pipe_failure_also_terminates_the_contained_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_refusals: int,
) -> None:
    real_read = native._read_pipe
    fail_now = threading.Event()
    real_marker_read = Path.read_text
    remaining_refusals = marker_refusals

    def read_marker(path, *args, **kwargs):
        nonlocal remaining_refusals
        if path == tmp_path / "parent-ready.json" and remaining_refusals:
            remaining_refusals -= 1
            raise PermissionError(13, "synthetic parent marker read refusal")
        return real_marker_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_marker)

    def fail_after_ready(handle):
        if fail_now.is_set():
            raise OSError("private-pipe-fault-sentinel")
        return real_read(handle)

    monkeypatch.setattr(native, "_read_pipe", fail_after_ready)
    with _tree(tmp_path) as exercise:
        assert remaining_refusals == 0
        fail_now.set()
        exercise.release.touch()
        outcome = exercise.wait()
        assert isinstance(outcome, native.WindowsProcessError)
        assert outcome.error.kind is ErrorKind.UNKNOWN_ERROR
        assert "sentinel" not in str(outcome)
        assert exercise.parent.exited(1500) and exercise.descendant.exited(1500)


def test_kill_on_job_close_survives_abrupt_controller_exit(tmp_path: Path) -> None:
    argv, nonce, child_ready, parent_ready, release = _tree_files(tmp_path, "hold")
    gate = tmp_path / "exit-controller"
    control = tmp_path / "controller.json"
    control.write_text(
        json.dumps({"argv": argv, "env": _environment(tmp_path), "gate": str(gate)}),
        encoding="utf-8",
    )
    controller_code = """
        import json, os, sys, threading, time
        from pathlib import Path
        from hermes_mailcloud.rclone._windows_process import run_windows_process
        control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        thread = threading.Thread(target=lambda: run_windows_process(
            control["argv"], environment=control["env"], timeout_seconds=20,
            max_capture_bytes=64), daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not Path(control["gate"]).exists():
            if time.monotonic() >= deadline:
                os._exit(93)
            time.sleep(0.005)
        os._exit(17)
    """
    controller = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(controller_code), str(control)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(tmp_path, source_import=True),
    )
    identities: list[_Identity] = []
    try:
        identities.append(_ready_identity(child_ready, nonce, "descendant"))
        identities.append(_ready_identity(parent_ready, nonce, "parent"))
        assert not any(identity.exited() for identity in identities)
        gate.touch()
        _stdout, stderr = controller.communicate(timeout=6)
        assert controller.returncode == 17, stderr.decode("utf-8", errors="replace")
        assert all(identity.exited(2000) for identity in identities), (
            "inherited Job handle or uncontained descendant survived the controller"
        )
    finally:
        gate.touch()
        release.touch()
        if controller.poll() is None:
            controller.terminate()
            controller.communicate(timeout=5)
        for identity in identities:
            if not identity.exited():
                win32api.TerminateProcess(identity.handle, 97)
                identity.exited(2000)
            identity.close()


def test_nested_job_context_keeps_inner_process_contained(tmp_path: Path) -> None:
    code = """
        import json, os, sys, win32api, win32job
        from hermes_mailcloud.rclone._windows_process import run_windows_process
        child = ("import json,win32api,win32job; p=win32api.GetCurrentProcess(); "
                 "print(json.dumps({'in_job': bool(win32job.IsProcessInJob(p, None))}))")
        result = run_windows_process(
            [sys.executable, "-c", child],
            environment={"SystemRoot": os.environ["SystemRoot"], "PATH": os.environ["PATH"]},
            timeout_seconds=3, max_capture_bytes=1024)
        in_job = bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None))
        print(json.dumps({"parent_in_job": in_job,
                          "inner_returncode": result.returncode,
                          "inner": json.loads(result.stdout)}))
    """
    result = _run(
        tmp_path, code, environment=_environment(tmp_path, source_import=True), timeout_seconds=6
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert payload == {"parent_in_job": True, "inner_returncode": 0, "inner": {"in_job": True}}


def test_child_cannot_break_away_from_the_job(tmp_path: Path) -> None:
    code = """
        import json, subprocess, sys
        child = ("import json,win32api,win32job; p=win32api.GetCurrentProcess(); "
                 "print(json.dumps({'in_job': bool(win32job.IsProcessInJob(p, None))}))")
        try:
            process = subprocess.Popen([sys.executable, "-c", child],
                creationflags=0x01000000, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            print(json.dumps({"breakaway_denied": True}))
        else:
            stdout, stderr = process.communicate(timeout=3)
            print(json.dumps({"breakaway_denied": False, "child": json.loads(stdout)}))
    """
    result = _run(tmp_path, code)
    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert payload.get("breakaway_denied") or payload["child"]["in_job"] is True
