"""Subprocess tests for rclone-backed file commands using a temporary fake binary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.helpers.cli_fake import CliFakeHarness, isolated_environment

_FILE_RESPONSES = {
    json.dumps(["lsjson", "fake:/Hermes"]): {
        "stdout": json.dumps(
            [
                {"Path": "private", "Name": "private", "IsDir": True},
                {
                    "Path": "private/notes.txt",
                    "Name": "notes.txt",
                    "IsDir": False,
                    "Size": 17,
                    "ModTime": "2026-07-25T01:02:03Z",
                },
            ]
        )
    },
    json.dumps(["lsjson", "fake:/Hermes/read-retry"]): {
        "sequence": [{"returncode": 1, "stderr": "network is unreachable"}, {"stdout": "[]"}]
    },
    json.dumps(["lsjson", "fake:/Hermes/private/notes.txt", "--stat", "--hash"]): {
        "stdout": json.dumps(
            {
                "Path": "private/notes.txt",
                "Name": "notes.txt",
                "IsDir": False,
                "Size": 17,
                "ModTime": "2026-07-25T01:02:03Z",
                "Hashes": {"MD5": "0123456789abcdef0123456789abcdef"},
            }
        )
    },
    "lsjson": {"returncode": 97, "stderr": "secret=cli-rclone-sentinel"},
    "copyto": {"download_text": "downloaded"},
}


def _fake_rclone(tmp_path: Path) -> CliFakeHarness:
    return CliFakeHarness.create(tmp_path)


def _run_cli(
    binary: CliFakeHarness, *arguments: str, extra_environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return binary.run(*arguments, responses=_FILE_RESPONSES, extra_environment=extra_environment)


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
    assert binary.recorded_calls() == [
        ["lsjson", "fake:/Hermes/read-retry"],
        ["lsjson", "fake:/Hermes/read-retry"],
    ]


def test_profile_read_retries_execute_each_write_operation_once(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    config = tmp_path / "config.toml"
    config.write_text("[profiles.default]\nretries = 1\n", encoding="utf-8")
    call_log = binary.calls
    environment = {}
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
    call_log = binary.calls
    environment = {}
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


def test_real_cli_transfer_keeps_unicode_spaces_and_metacharacters_literal(tmp_path: Path) -> None:
    harness = CliFakeHarness.create(tmp_path)
    folder = tmp_path / "space ü &;$% [literal]"
    folder.mkdir()
    source = folder / "input 'quoted'.txt"
    source.write_text("private", encoding="utf-8")
    target = folder / "output 'quoted'.txt"
    remote = "/Hermes/private/space ü &;$%/report 'quoted'.txt"

    uploaded = _run_cli(harness, "upload", str(source), remote, "--json")
    downloaded = _run_cli(harness, "download", remote, str(target), "--json")

    assert uploaded.returncode == downloaded.returncode == 0
    assert uploaded.stderr == downloaded.stderr == ""
    assert json.loads(uploaded.stdout)["result"]["local_path"] == str(source)
    assert json.loads(downloaded.stdout)["result"]["local_path"] == str(target)
    calls = harness.recorded_calls()
    assert calls[0] == ["copyto", str(source), "fake:" + remote, "--immutable"]
    assert calls[1][:2] == ["copyto", "fake:" + remote]
    assert Path(calls[1][2]).parent == folder
    assert target.read_text(encoding="utf-8") == "downloaded"
    assert list(folder.glob("*.hermes-mailcloud-part")) == []


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
    binary = _fake_rclone(tmp_path)
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
        env=isolated_environment(tmp_path),
    )
    missing_config = _run_cli(
        binary,
        "--config",
        str(tmp_path / "missing.toml"),
        "ls",
        "/Hermes",
        "--json",
    )
    backend_failure = _run_cli(binary, "ls", "/unexpected", "--json")

    assert no_remote.returncode == 5
    assert json.loads(no_remote.stdout)["error"]["kind"] == "remote_not_configured"
    assert no_remote.stderr == ""
    assert missing_config.returncode == 3
    assert json.loads(missing_config.stdout)["error"]["kind"] == "config_error"
    assert missing_config.stderr == ""
    assert backend_failure.returncode == 1
    assert json.loads(backend_failure.stdout)["error"]["kind"] == "unknown_error"
    assert "cli-rclone-sentinel" not in backend_failure.stdout + backend_failure.stderr
