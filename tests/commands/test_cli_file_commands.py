"""Subprocess tests for rclone-backed file commands using a temporary fake binary."""

from __future__ import annotations

import json
import os
import stat as stat_module
import subprocess
import sys
from pathlib import Path

FAKE_RCLONE = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

command, *args = sys.argv[1:]
with Path(__file__).with_name("rclone.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps([command, *args]) + "\\n")
if command == "lsjson" and args == ["fake:/Hermes"]:
    print(json.dumps([
        {"Path": "private", "Name": "private", "IsDir": True},
        {
            "Path": "private/notes.txt", "Name": "notes.txt", "IsDir": False,
            "Size": 17, "ModTime": "2026-07-25T01:02:03Z",
        },
    ]))
    raise SystemExit(0)
if command == "lsjson" and args == ["fake:/Hermes/read-retry"]:
    retry_marker = Path(__file__).with_name("read-retry-attempt")
    if not retry_marker.exists():
        retry_marker.write_text("first", encoding="utf-8")
        sys.stderr.write("network is unreachable")
        raise SystemExit(1)
    print("[]")
    raise SystemExit(0)
if command == "lsjson" and args == ["fake:/Hermes/private/notes.txt", "--stat", "--hash"]:
    print(json.dumps({
        "Path": "private/notes.txt", "Name": "notes.txt", "IsDir": False, "Size": 17,
        "ModTime": "2026-07-25T01:02:03Z", "Hashes": {"MD5": "0123456789abcdef0123456789abcdef"},
    }))
    raise SystemExit(0)
if command == "mkdir" and args == ["fake:/Hermes/private/reports"]:
    raise SystemExit(0)
if command == "copyto" and len(args) == 3 and args[1:] == [
    "fake:/Hermes/private/upload.txt", "--immutable"
]:
    raise SystemExit(0)
if command == "copyto" and len(args) == 2 and args[0] == "fake:/Hermes/private/notes.txt":
    Path(args[1]).write_text("downloaded", encoding="utf-8")
    raise SystemExit(0)
if command == "moveto" and args == [
    "fake:/Hermes/private/source.txt", "fake:/Hermes/private/moved.txt", "--immutable"
]:
    raise SystemExit(0)
if command == "copyto" and args == [
    "fake:/Hermes/private/source.txt", "fake:/Hermes/private/copied.txt", "--immutable"
]:
    raise SystemExit(0)
if command == "deletefile" and args == ["fake:/Hermes/private/old.txt"]:
    raise SystemExit(0)
sys.stderr.write("unexpected fake rclone command secret=cli-rclone-sentinel\\n")
raise SystemExit(97)
"""


def _fake_rclone(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-rclone"
    binary.write_text(FAKE_RCLONE, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat_module.S_IXUSR)
    return binary


def _run_cli(
    binary: Path, *arguments: str, extra_environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "HMC_REMOTE": "fake:",
        "HMC_RCLONE_PATH": str(binary),
        **(extra_environment or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def test_profile_retries_remain_available_to_safe_read_commands(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    config = tmp_path / "config.toml"
    config.write_text("[profiles.default]\nretries = 1\n", encoding="utf-8")

    result = _run_cli(
        binary,
        "--config",
        str(config),
        "ls",
        "/Hermes/read-retry",
        "--json",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"] == {
        "remote_path": "/Hermes/read-retry",
        "items": [],
    }
    assert [json.loads(line) for line in (tmp_path / "rclone.jsonl").read_text().splitlines()] == [
        ["lsjson", "fake:/Hermes/read-retry"],
        ["lsjson", "fake:/Hermes/read-retry"],
    ]


def test_profile_read_retries_execute_each_write_operation_once(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    config = tmp_path / "config.toml"
    config.write_text("[profiles.default]\nretries = 1\n", encoding="utf-8")
    call_log = tmp_path / "rclone.jsonl"
    environment = {"FAKE_RCLONE_CALL_LOG": str(call_log)}
    upload_source = tmp_path / "upload.txt"
    upload_source.write_text("private", encoding="utf-8")
    download_target = tmp_path / "downloaded.txt"
    global_arguments = ("--config", str(config))

    results = [
        _run_cli(
            binary,
            *global_arguments,
            "mkdir",
            "/Hermes/private/reports",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            *global_arguments,
            "upload",
            str(upload_source),
            "/Hermes/private/upload.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            *global_arguments,
            "download",
            "/Hermes/private/notes.txt",
            str(download_target),
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            *global_arguments,
            "mv",
            "/Hermes/private/source.txt",
            "/Hermes/private/moved.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            *global_arguments,
            "cp",
            "/Hermes/private/source.txt",
            "/Hermes/private/copied.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            *global_arguments,
            "rm",
            "/Hermes/private/old.txt",
            "--yes",
            "--json",
            extra_environment=environment,
        ),
    ]

    assert all(result.returncode == 0 and result.stderr == "" for result in results)
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert calls[0] == ["mkdir", "fake:/Hermes/private/reports"]
    assert calls[1] == [
        "copyto",
        str(upload_source),
        "fake:/Hermes/private/upload.txt",
        "--immutable",
    ]
    assert calls[2][:2] == ["copyto", "fake:/Hermes/private/notes.txt"]
    assert Path(calls[2][2]).parent == download_target.parent
    assert calls[3] == [
        "moveto",
        "fake:/Hermes/private/source.txt",
        "fake:/Hermes/private/moved.txt",
        "--immutable",
    ]
    assert calls[4] == [
        "copyto",
        "fake:/Hermes/private/source.txt",
        "fake:/Hermes/private/copied.txt",
        "--immutable",
    ]
    assert calls[5] == ["deletefile", "fake:/Hermes/private/old.txt"]
    assert len(calls) == 6


def test_explicit_write_retries_are_rejected_before_any_backend_call(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    call_log = tmp_path / "rclone.jsonl"
    environment = {"FAKE_RCLONE_CALL_LOG": str(call_log)}
    upload_source = tmp_path / "upload.txt"
    upload_source.write_text("private", encoding="utf-8")

    results = [
        _run_cli(
            binary,
            "--retries",
            "1",
            "mkdir",
            "/Hermes/private/reports",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            "--retries",
            "1",
            "upload",
            str(upload_source),
            "/Hermes/private/upload.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            "--retries",
            "1",
            "download",
            "/Hermes/private/notes.txt",
            str(tmp_path / "downloaded.txt"),
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            "--retries",
            "1",
            "mv",
            "/Hermes/private/source.txt",
            "/Hermes/private/moved.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            "--retries",
            "1",
            "cp",
            "/Hermes/private/source.txt",
            "/Hermes/private/copied.txt",
            "--json",
            extra_environment=environment,
        ),
        _run_cli(
            binary,
            "--retries",
            "1",
            "rm",
            "/Hermes/private/old.txt",
            "--yes",
            "--json",
            extra_environment=environment,
        ),
    ]

    assert all(result.returncode == 2 and result.stderr == "" for result in results)
    assert all(
        json.loads(result.stdout)["error"]["kind"] == "invalid_arguments" for result in results
    )
    assert not call_log.exists()


def test_file_commands_emit_stable_json_from_a_real_fake_subprocess(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    upload_source = tmp_path / "upload.txt"
    upload_source.write_text("private", encoding="utf-8")
    download_target = tmp_path / "downloaded.txt"

    listed = _run_cli(binary, "ls", "/Hermes", "--json")
    inspected = _run_cli(binary, "stat", "/Hermes/private/notes.txt", "--json")
    created = _run_cli(binary, "mkdir", "/Hermes/private/reports", "--json")
    uploaded = _run_cli(
        binary, "upload", str(upload_source), "/Hermes/private/upload.txt", "--json"
    )
    downloaded = _run_cli(
        binary, "download", "/Hermes/private/notes.txt", str(download_target), "--json"
    )
    moved = _run_cli(
        binary, "mv", "/Hermes/private/source.txt", "/Hermes/private/moved.txt", "--json"
    )
    copied = _run_cli(
        binary, "cp", "/Hermes/private/source.txt", "/Hermes/private/copied.txt", "--json"
    )
    results = [listed, inspected, created, uploaded, downloaded, moved, copied]

    assert all(result.returncode == 0 for result in results)
    assert all(result.stderr == "" for result in results)
    assert json.loads(listed.stdout) == {
        "ok": True,
        "operation": "ls",
        "profile": "default",
        "remote": "fake:",
        "result": {
            "items": [
                {"name": "private", "path": "/Hermes/private", "type": "directory"},
                {
                    "modified": "2026-07-25T01:02:03Z",
                    "name": "notes.txt",
                    "path": "/Hermes/private/notes.txt",
                    "size": 17,
                    "type": "file",
                },
            ],
            "remote_path": "/Hermes",
        },
    }
    assert json.loads(inspected.stdout)["result"] == {
        "remote_path": "/Hermes/private/notes.txt",
        "type": "file",
        "size": 17,
        "modified": "2026-07-25T01:02:03Z",
        "hashes": {"MD5": "0123456789abcdef0123456789abcdef"},
    }
    assert json.loads(created.stdout)["result"] == {
        "remote_path": "/Hermes/private/reports",
        "created": True,
    }
    assert json.loads(uploaded.stdout)["result"] == {
        "local_path": str(upload_source),
        "remote_path": "/Hermes/private/upload.txt",
        "published": False,
        "bytes": 7,
        "overwrite": "never",
    }
    assert json.loads(downloaded.stdout)["result"] == {
        "remote_path": "/Hermes/private/notes.txt",
        "local_path": str(download_target),
        "overwrite": "never",
        "bytes": 10,
        "updated": True,
    }
    assert download_target.read_text(encoding="utf-8") == "downloaded"
    assert json.loads(moved.stdout)["result"] == {
        "source_path": "/Hermes/private/source.txt",
        "target_path": "/Hermes/private/moved.txt",
        "overwrite": "never",
    }
    assert json.loads(copied.stdout)["result"] == {
        "source_path": "/Hermes/private/source.txt",
        "target_path": "/Hermes/private/copied.txt",
        "overwrite": "never",
    }


def test_mkdir_dry_run_never_starts_the_fake_subprocess(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)

    result = _run_cli(binary, "mkdir", "/Hermes/private/reports", "--json", "--dry-run")

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"]["dry_run"] is True


def test_transfer_dry_runs_never_start_the_fake_subprocess(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    upload_source = tmp_path / "upload.txt"
    upload_source.write_text("private", encoding="utf-8")
    commands = [
        ("upload", str(upload_source), "/Hermes/private/upload.txt"),
        ("download", "/Hermes/private/notes.txt", str(tmp_path / "downloaded.txt")),
        ("mv", "/Hermes/private/source.txt", "/Hermes/private/moved.txt"),
        ("cp", "/Hermes/private/source.txt", "/Hermes/private/copied.txt"),
    ]

    results = [_run_cli(binary, *command, "--json", "--dry-run") for command in commands]

    assert all(result.returncode == 0 and result.stderr == "" for result in results)
    assert all(json.loads(result.stdout)["result"]["dry_run"] is True for result in results)


def test_file_commands_return_typed_config_and_backend_errors_without_raw_output(
    tmp_path: Path,
) -> None:
    empty_config = tmp_path / "config.toml"
    empty_config.write_text("[profiles.default]\n", encoding="utf-8")
    no_remote = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_mailcloud.cli",
            "--config",
            str(empty_config),
            "ls",
            "/Hermes",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={key: value for key, value in os.environ.items() if not key.startswith("HMC_")},
    )
    missing_config = _run_cli(
        _fake_rclone(tmp_path),
        "--config",
        str(tmp_path / "missing.toml"),
        "ls",
        "/Hermes",
        "--json",
    )
    backend_failure = _run_cli(_fake_rclone(tmp_path), "ls", "/unexpected", "--json")

    assert no_remote.returncode == 5
    assert json.loads(no_remote.stdout)["error"]["kind"] == "remote_not_configured"
    assert no_remote.stderr == ""
    assert missing_config.returncode == 3
    assert json.loads(missing_config.stdout)["error"]["kind"] == "config_error"
    assert missing_config.stderr == ""
    assert backend_failure.returncode == 1
    assert json.loads(backend_failure.stdout)["error"]["kind"] == "unknown_error"
    assert "cli-rclone-sentinel" not in backend_failure.stdout + backend_failure.stderr
