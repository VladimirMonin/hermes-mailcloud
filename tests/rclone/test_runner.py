"""Offline subprocess-boundary tests using a deterministic fake executable."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.rclone.parser import RcloneParseError, parse_lsjson
from hermes_mailcloud.rclone.runner import (
    RcloneResult,
    RcloneRunner,
    RcloneRunnerError,
    deterministic_environment,
    map_rclone_error,
)

ROOT = Path(__file__).parent
FAKE_RCLONE = ROOT / "fake_rclone.py"


def _runner(*, max_capture_bytes: int = 64 * 1024) -> RcloneRunner:
    environment = {"PATH": os.environ.get("PATH", "")}
    if os.name == "nt":
        environment["SystemRoot"] = os.environ.get("SystemRoot", "")
    return RcloneRunner(
        (sys.executable, str(FAKE_RCLONE)),
        environment=environment,
        max_capture_bytes=max_capture_bytes,
    )


def _expected_environment(*, system_root: str | None) -> dict[str, str]:
    expected = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    if system_root is not None:
        expected["SystemRoot"] = system_root
    return _normalized_environment(expected)


def _normalized_environment(environment: dict[str, str]) -> dict[str, str]:
    if os.name == "nt":
        return {key.upper(): value for key, value in environment.items()}
    return dict(environment)


def test_runner_uses_literal_argv_and_a_deterministic_minimal_environment() -> None:
    result = _runner().run(["success", "literal;not-a-shell-command"], timeout_seconds=1)

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["arguments"] == ["literal;not-a-shell-command"]
    assert _normalized_environment(payload["environment"]) == _expected_environment(
        system_root=os.environ.get("SystemRoot") if os.name == "nt" else None
    )


def test_deterministic_environment_keeps_only_allowlisted_keys_case_insensitively() -> None:
    source = {
        "path": "synthetic-path-value",
        "HOME": "synthetic-home",
        "RCLONE_CONFIG": "synthetic-rclone-config",
        "SystemRoot": "synthetic-system-root",
        "WINDIR": "forbidden-windir",
        "USERPROFILE": "forbidden-profile",
        "APPDATA": "forbidden-appdata",
        "LOCALAPPDATA": "forbidden-localappdata",
        "TEMP": "forbidden-temp",
        "TMP": "forbidden-tmp",
        "HMC_TOKEN": "forbidden-hmc-token",
        "RCLONE_PASSWORD": "forbidden-rclone-password",
        "HTTP_PROXY": "forbidden-proxy",
    }

    environment = deterministic_environment(source)

    expected = {
        "PATH": "synthetic-path-value" if os.name == "nt" else os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "HOME": "synthetic-home",
        "RCLONE_CONFIG": "synthetic-rclone-config",
    }
    if os.name == "nt":
        expected["SystemRoot"] = "synthetic-system-root"
    assert environment == expected
    rendered = json.dumps(environment)
    assert "forbidden" not in rendered


def test_runner_maps_nonzero_fake_output_without_serializing_raw_diagnostics() -> None:
    result = _runner().run(["error"], timeout_seconds=1)
    error = map_rclone_error(result)

    assert result.returncode == 17
    assert error.kind is ErrorKind.NETWORK_ERROR
    rendered = json.dumps(error.to_payload())
    assert "runner-secret-sentinel" not in rendered
    assert error.details == {"backend_exit_code": 17}


@pytest.mark.parametrize(
    ("diagnostic", "expected_kind"),
    [
        ("didn't find section in config file", ErrorKind.REMOTE_NOT_CONFIGURED),
        ("permission denied", ErrorKind.ACCESS_DENIED),
        ("file exists", ErrorKind.CONFLICT),
        ("operation not supported", ErrorKind.BACKEND_UNSUPPORTED),
        ("object not found", ErrorKind.NOT_FOUND),
        ("unclassified provider failure", ErrorKind.UNKNOWN_ERROR),
    ],
)
def test_runner_error_mapper_uses_frozen_error_kinds(
    diagnostic: str, expected_kind: ErrorKind
) -> None:
    error = map_rclone_error(RcloneResult(17, "", diagnostic, duration_ms=0))

    assert error.kind is expected_kind
    assert error.details == {"backend_exit_code": 17}


def test_runner_enforces_timeout_with_a_typed_error() -> None:
    with pytest.raises(RcloneRunnerError) as caught:
        _runner().run(["timeout"], timeout_seconds=0.05)

    assert caught.value.error.kind is ErrorKind.TIMEOUT
    assert caught.value.error.exit_code == 14
    assert "timed out" in caught.value.error.message


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc").is_dir(),
    reason="process-group semantics are exercised on Linux",
)
def test_runner_timeout_kills_descendants_holding_output_pipes_promptly(tmp_path: Path) -> None:
    pid_path = tmp_path / "descendant.pid"
    started = time.monotonic()

    with pytest.raises(RcloneRunnerError) as caught:
        _runner().run(["timeout-descendant", str(pid_path)], timeout_seconds=2)

    elapsed = time.monotonic() - started
    ready = json.loads(pid_path.read_text(encoding="ascii"))
    assert ready["ready"] is True and ready["start_ticks"]
    assert caught.value.error.kind is ErrorKind.TIMEOUT
    assert elapsed < 3.5
    assert not _process_is_running(ready["pid"], ready["start_ticks"])


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc").is_dir(),
    reason="process-group semantics are exercised on Linux",
)
def test_runner_timeout_bounds_reader_drain_after_parent_exit(tmp_path: Path) -> None:
    pid_path = tmp_path / "descendant.pid"
    started = time.monotonic()

    with pytest.raises(RcloneRunnerError) as caught:
        _runner().run(["exit-with-descendant", str(pid_path)], timeout_seconds=2)

    elapsed = time.monotonic() - started
    ready = json.loads(pid_path.read_text(encoding="ascii"))
    assert ready["ready"] is True and ready["start_ticks"]
    assert caught.value.error.kind is ErrorKind.TIMEOUT
    assert elapsed < 3.5
    assert not _process_is_running(ready["pid"], ready["start_ticks"])


def test_fake_malformed_output_exercises_the_parser_failure_boundary() -> None:
    result = _runner().run(["malformed"], timeout_seconds=1)

    with pytest.raises(RcloneParseError) as caught:
        parse_lsjson(result.stdout, root="/Hermes")

    assert caught.value.error.kind is ErrorKind.PARSE_ERROR


def test_runner_bounds_both_streams_and_marks_truncation() -> None:
    result = _runner(max_capture_bytes=31).run(["overflow"], timeout_seconds=1)

    assert len(result.stdout.encode("utf-8")) <= 31
    assert len(result.stderr.encode("utf-8")) <= 31
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


@pytest.mark.skipif(os.name != "nt", reason="Windows executable resolution")
def test_windows_resolves_a_single_exe_from_only_the_supplied_path(tmp_path: Path) -> None:
    environment = {
        "PATH": str(Path(sys.executable).parent),
        "SystemRoot": os.environ["SystemRoot"],
        "PATHEXT": ".CMD;.BAT",
    }
    result = RcloneRunner(
        (Path(sys.executable).stem, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))"),
        environment=environment,
    ).run(["space ü &;|$%", "C:\\literal\\", 'a"b'], timeout_seconds=2)
    assert result.returncode == 0
    assert json.loads(result.stdout) == ["space ü &;|$%", "C:\\literal\\", 'a"b']


@pytest.mark.skipif(os.name != "nt", reason="Windows executable resolution")
def test_windows_never_uses_a_shell_wrapper_or_an_implicit_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    (tmp_path / "shadow.exe").write_bytes(b"not-an-executable")
    wrapper = tmp_path / "wrapper.cmd"
    marker = tmp_path / "must-not-execute"
    wrapper.write_text(f"echo unsafe > {marker}\n", encoding="utf-8")
    for binary in ("shadow", str(wrapper), f"{sys.executable} --version"):
        with pytest.raises(RcloneRunnerError) as caught:
            RcloneRunner(
                binary,
                environment={
                    "PATH": str(empty_path),
                    "SystemRoot": os.environ["SystemRoot"],
                },
            ).run([], timeout_seconds=1)
        assert caught.value.error.kind is ErrorKind.RCLONE_NOT_FOUND
        assert "must-not-execute" not in str(caught.value)
    assert not marker.exists()


def _process_is_running(pid: int, start_ticks: str) -> bool:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return False
    return fields[0] != "Z" and fields[19] == start_ticks
