"""Fake-backend and CLI tests for guarded permanent remote removal."""

from __future__ import annotations

import json
import os
import stat as stat_module
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_mailcloud.commands.remove import RemoveCommand
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult


@dataclass
class RecordingBackend:
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        return RcloneResult(0, "", "", 1)


def _config(*, remote: str | None = "mailru:") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=None,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


@pytest.mark.parametrize(("recursive", "command"), [(False, "deletefile"), (True, "purge")])
def test_rm_executes_one_confirmed_rclone_command(recursive: bool, command: str) -> None:
    backend = RecordingBackend()

    result = RemoveCommand(backend, _config(), timeout_seconds=9).run(
        "/Hermes/private/./old.txt", recursive=recursive, yes=True
    )

    assert result == {
        "remote_path": "/Hermes/private/old.txt",
        "recursive": recursive,
        "deleted": True,
    }
    assert backend.calls == [((command, "mailru:/Hermes/private/old.txt"), 9)]


def test_rm_dry_run_validates_without_confirmation_or_backend_use() -> None:
    backend = RecordingBackend()

    result = RemoveCommand(backend, _config(), timeout_seconds=60).run(
        "/Hermes/private/old.txt", dry_run=True
    )

    assert result == {
        "remote_path": "/Hermes/private/old.txt",
        "recursive": False,
        "dry_run": True,
        "plan": [
            {"step": "validate_arguments", "status": "planned"},
            {"step": "execute", "status": "planned"},
        ],
    }
    assert backend.calls == []


@pytest.mark.parametrize(
    "remote_path",
    ["/", "/Hermes", "/TEST", "/Hermes/private", "/Hermes/public", "/Hermes/.tmp"],
)
def test_rm_rejects_protected_roots_before_backend_use(remote_path: str) -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        RemoveCommand(backend, _config(), timeout_seconds=60).run(remote_path, yes=True)

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_rm_requires_confirmation_and_rejects_write_retries_before_backend_use() -> None:
    backend = RecordingBackend()
    command = RemoveCommand(backend, _config(), timeout_seconds=60)

    with pytest.raises(MailCloudError) as unconfirmed:
        command.run("/Hermes/private/old.txt")
    with pytest.raises(MailCloudError) as retried:
        command.run("/Hermes/private/old.txt", yes=True, retries=1)

    assert unconfirmed.value.error.kind is ErrorKind.CONFIRMATION_REQUIRED
    assert retried.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_rm_requires_a_configured_remote_even_for_a_dry_run() -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        RemoveCommand(backend, _config(remote=None), timeout_seconds=60).run(
            "/Hermes/private/old.txt", dry_run=True
        )

    assert caught.value.error.kind is ErrorKind.REMOTE_NOT_CONFIGURED
    assert backend.calls == []


_FAKE_RCLONE = """#!/usr/bin/env python3
import sys

if sys.argv[1:] == ["deletefile", "fake:/Hermes/private/old.txt"]:
    raise SystemExit(0)
if sys.argv[1:] == ["purge", "fake:/Hermes/private/tree"]:
    raise SystemExit(0)
raise SystemExit(97)
"""


def _fake_rclone(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-rclone"
    binary.write_text(_FAKE_RCLONE, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat_module.S_IXUSR)
    return binary


def _run_cli(binary: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HMC_REMOTE": "fake:", "HMC_RCLONE_PATH": str(binary)},
    )


def test_cli_rm_serializes_success_and_rejects_unsafe_requests_before_rclone(
    tmp_path: Path,
) -> None:
    binary = _fake_rclone(tmp_path)
    deleted_file = _run_cli(binary, "rm", "/Hermes/private/old.txt", "--json", "--yes")
    deleted_tree = _run_cli(binary, "rm", "/Hermes/private/tree", "--recursive", "--json", "--yes")
    missing_confirmation = _run_cli(binary, "rm", "/Hermes/private/old.txt", "--json")
    protected_root = _run_cli(binary, "rm", "/", "--json", "--yes")

    assert deleted_file.returncode == 0
    assert deleted_file.stderr == ""
    assert json.loads(deleted_file.stdout)["result"] == {
        "remote_path": "/Hermes/private/old.txt",
        "recursive": False,
        "deleted": True,
    }
    assert deleted_tree.returncode == 0
    assert deleted_tree.stderr == ""
    assert json.loads(deleted_tree.stdout)["result"] == {
        "remote_path": "/Hermes/private/tree",
        "recursive": True,
        "deleted": True,
    }
    assert missing_confirmation.returncode == 9
    assert json.loads(missing_confirmation.stdout)["error"]["kind"] == "confirmation_required"
    assert protected_root.returncode == 2
    assert json.loads(protected_root.stdout)["error"]["kind"] == "invalid_arguments"
