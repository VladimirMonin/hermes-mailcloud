"""Schema-conformant fake/golden tests for deterministic v0.1 batch execution."""

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

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud.batch import BatchCommands, BatchPlan, parse_batch_document, parse_batch_file
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload, MailCloudError
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunnerError

FIXTURES = Path(__file__).with_name("fixtures")


@dataclass
class RecordingBackend:
    outcomes: list[RcloneResult | MailCloudError] = field(default_factory=list)
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, MailCloudError):
            raise outcome
        return outcome


def _config(*, journal: Path | None = None, remote: str | None = "mailru:") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=journal,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


def _commands(backend: RecordingBackend, *, journal: Path | None = None) -> BatchCommands:
    return BatchCommands(backend, _config(journal=journal), timeout_seconds=9, read_retries=0)


def _plan(*operations: dict[str, object], continue_on_error: bool = False) -> BatchPlan:
    return parse_batch_document(
        {
            "version": 1,
            "defaults": {"continue_on_error": continue_on_error},
            "operations": list(operations),
        }
    )


def test_dry_run_matches_the_golden_plan_and_never_calls_the_backend() -> None:
    backend = RecordingBackend()
    plan = parse_batch_file(FIXTURES / "dry-run-plan.json")

    execution = _commands(backend).run(plan, dry_run=True, yes=False)

    assert execution.is_partial is False
    assert execution.result == json.loads(
        (FIXTURES / "dry-run-result.json").read_text(encoding="utf-8")
    )
    assert backend.calls == []


def test_discriminated_plan_validation_rejects_unexpected_per_operation_fields() -> None:
    with pytest.raises(MailCloudError) as caught:
        parse_batch_document(
            {
                "version": 1,
                "operations": [
                    {
                        "op": "ls",
                        "remote_path": "/Hermes",
                        "local_path": "must-not-be-accepted",
                    }
                ],
            }
        )

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS


def test_parser_accepts_every_discriminated_v0_1_operation_shape() -> None:
    plan = parse_batch_document(
        {
            "version": 1,
            "operations": [
                {"op": "ls", "remote_path": "/Hermes", "recursive": True},
                {"op": "stat", "remote_path": "/Hermes/private/report.txt"},
                {
                    "op": "mkdir",
                    "remote_path": "/Hermes/private/reports",
                    "parents": True,
                    "exist_ok": True,
                },
                {
                    "op": "upload",
                    "local_path": "./report.txt",
                    "remote_path": "/Hermes/private/report.txt",
                    "overwrite": "always",
                },
                {
                    "op": "download",
                    "remote_path": "/Hermes/private/report.txt",
                    "local_path": "./downloaded.txt",
                    "overwrite": "if-newer",
                },
                {
                    "op": "mv",
                    "src_remote_path": "/Hermes/private/source.txt",
                    "dst_remote_path": "/Hermes/private/moved.txt",
                },
                {
                    "op": "cp",
                    "src_remote_path": "/Hermes/private/source.txt",
                    "dst_remote_path": "/Hermes/private/copied.txt",
                },
                {"op": "rm", "remote_path": "/Hermes/private/old.txt", "recursive": True},
                {
                    "op": "publish",
                    "local_path": "./report.txt",
                    "remote_path": "/Hermes/public/report.txt",
                },
                {"op": "link", "remote_path": "/Hermes/public/report.txt"},
            ],
        }
    )

    assert [operation.operation for operation in plan.operations] == [
        "ls",
        "stat",
        "mkdir",
        "upload",
        "download",
        "mv",
        "cp",
        "rm",
        "publish",
        "link",
    ]


def test_outer_confirmation_rejects_any_write_before_preflight_or_backend_use() -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        _commands(backend).run(
            _plan({"op": "mkdir", "remote_path": "/Hermes/private/reports"}),
            dry_run=False,
            yes=False,
        )

    assert caught.value.error.kind is ErrorKind.CONFIRMATION_REQUIRED
    assert backend.calls == []


def test_real_public_batch_requires_journal_before_any_preflight_or_backend_use() -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        _commands(backend).run(
            _plan({"op": "link", "remote_path": "/Hermes/public/report.txt"}),
            dry_run=False,
            yes=True,
        )

    assert caught.value.error.kind is ErrorKind.CONFIG_ERROR
    assert backend.calls == []


def _make_journal_preflight_fail(
    journal: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if failure == "insecure_lock":
        lock_path = journal.with_name(f".{journal.name}.lock")
        lock_path.write_bytes(b"")
        lock_path.chmod(0o644)
        return
    if failure == "symlink_lock":
        journal.with_name(f".{journal.name}.lock").symlink_to("untrusted-lock-target")
        return
    if failure == "invalid_permission_journal":
        journal.write_bytes(b'{"version":1}\n')
        journal.chmod(0o644)
        return
    if failure == "oversized_journal":
        journal.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))
        journal.chmod(0o600)
        return
    if failure == "unreadable_journal":
        journal.write_bytes(b'{"version":1}\n')
        journal.chmod(0o600)
        original_open = journal_module.os.open

        def deny_journal_open(
            candidate: str | Path,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if Path(candidate) == journal:
                raise PermissionError("journal read denied")
            return original_open(candidate, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(journal_module.os, "open", deny_journal_open)
        return
    raise AssertionError(f"unknown journal preflight failure: {failure}")


@pytest.mark.parametrize("public_operation", ["publish", "link"])
@pytest.mark.parametrize(
    "failure",
    [
        "insecure_lock",
        "symlink_lock",
        "invalid_permission_journal",
        "unreadable_journal",
        "oversized_journal",
    ],
)
def test_batch_public_journal_preflight_fails_before_any_backend_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public_operation: str, failure: str
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = tmp_path / "links.jsonl"
    _make_journal_preflight_fail(journal, failure, monkeypatch)
    backend = RecordingBackend()
    public_fields: dict[str, object] = {
        "op": public_operation,
        "remote_path": "/Hermes/public/report.txt",
    }
    if public_operation == "publish":
        public_fields["local_path"] = str(source)

    with pytest.raises(JournalError):
        _commands(backend, journal=journal).run(
            _plan(
                {"op": "mkdir", "remote_path": "/Hermes/private/before-public"},
                public_fields,
            ),
            dry_run=False,
            yes=True,
        )

    assert backend.calls == []


def test_continue_on_error_returns_ordered_partial_failure_items() -> None:
    backend = RecordingBackend(
        [
            RcloneRunnerError(
                ErrorPayload(ErrorKind.NETWORK_ERROR, "rclone network request failed")
            ),
            RcloneResult(0, "", "", 1),
        ]
    )

    execution = _commands(backend).run(
        _plan(
            {"op": "mkdir", "remote_path": "/Hermes/private/failed"},
            {"op": "mkdir", "remote_path": "/Hermes/private/succeeded"},
            continue_on_error=True,
        ),
        dry_run=False,
        yes=True,
    )

    assert execution.is_partial is True
    assert execution.result == {
        "status": "partial_failure",
        "exit_code": 11,
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "items": [
            {
                "index": 0,
                "operation": "mkdir",
                "ok": False,
                "error": {
                    "kind": "network_error",
                    "message": "rclone network request failed",
                    "exit_code": 10,
                },
            },
            {
                "index": 1,
                "operation": "mkdir",
                "ok": True,
                "result": {"remote_path": "/Hermes/private/succeeded", "created": True},
            },
        ],
    }
    assert [call[0] for call in backend.calls] == [
        ("mkdir", "mailru:/Hermes/private/failed"),
        ("mkdir", "mailru:/Hermes/private/succeeded"),
    ]


def test_default_stop_after_error_preserves_attempt_order_without_running_later_operations() -> (
    None
):
    backend = RecordingBackend(
        [RcloneRunnerError(ErrorPayload(ErrorKind.NETWORK_ERROR, "rclone network request failed"))]
    )

    execution = _commands(backend).run(
        _plan(
            {"op": "mkdir", "remote_path": "/Hermes/private/failed"},
            {"op": "mkdir", "remote_path": "/Hermes/private/not-run"},
        ),
        dry_run=False,
        yes=True,
    )

    assert execution.is_partial is True
    assert execution.result["total"] == 1
    assert execution.result["items"][0]["index"] == 0
    assert [call[0] for call in backend.calls] == [("mkdir", "mailru:/Hermes/private/failed")]


_FAKE_RCLONE = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

command, *args = sys.argv[1:]
with Path(__file__).with_name("rclone.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps([command, *args]) + "\\n")
if command == "mkdir" and args == ["fake:/Hermes/private/reports"]:
    raise SystemExit(0)
if command == "mkdir" and args == ["fake:/Hermes/private/failed"]:
    sys.stderr.write("network is unreachable batch-backend-sentinel")
    raise SystemExit(1)
if command == "mkdir" and args == ["fake:/Hermes/private/succeeded"]:
    raise SystemExit(0)
sys.stderr.write("unexpected fake rclone command secret=batch-rclone-sentinel")
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


def test_cli_executes_the_validated_plan_and_emits_a_golden_completed_envelope(
    tmp_path: Path,
) -> None:
    binary = _fake_rclone(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": [{"op": "mkdir", "remote_path": "/Hermes/private/reports"}],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(binary, "batch", str(plan_path), "--json", "--yes")

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "ok": True,
        "operation": "batch",
        "profile": "default",
        "remote": "fake:",
        "result": {
            "status": "completed",
            "total": 1,
            "succeeded": 1,
            "failed": 0,
            "items": [
                {
                    "index": 0,
                    "operation": "mkdir",
                    "ok": True,
                    "result": {"remote_path": "/Hermes/private/reports", "created": True},
                }
            ],
        },
    }
    assert [json.loads(line) for line in (tmp_path / "rclone.jsonl").read_text().splitlines()] == [
        ["mkdir", "fake:/Hermes/private/reports"]
    ]


def test_cli_partial_failure_exits_11_and_never_leaks_fake_backend_diagnostics(
    tmp_path: Path,
) -> None:
    binary = _fake_rclone(tmp_path)
    plan_path = tmp_path / "partial.json"
    plan_path.write_text(
        json.dumps(
            {
                "version": 1,
                "defaults": {"continue_on_error": True},
                "operations": [
                    {"op": "mkdir", "remote_path": "/Hermes/private/failed"},
                    {"op": "mkdir", "remote_path": "/Hermes/private/succeeded"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(binary, "batch", str(plan_path), "--json", "--yes")

    assert result.returncode == 11
    assert result.stderr == ""
    assert "batch-backend-sentinel" not in result.stdout
    assert json.loads(result.stdout)["result"] == {
        "status": "partial_failure",
        "exit_code": 11,
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "items": [
            {
                "index": 0,
                "operation": "mkdir",
                "ok": False,
                "error": {
                    "kind": "network_error",
                    "message": "rclone network request failed",
                    "exit_code": 10,
                },
            },
            {
                "index": 1,
                "operation": "mkdir",
                "ok": True,
                "result": {"remote_path": "/Hermes/private/succeeded", "created": True},
            },
        ],
    }


def test_cli_batch_dry_run_validates_without_launching_the_fake_backend(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path)
    plan_path = tmp_path / "dry-run.json"
    plan_path.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": [{"op": "mkdir", "remote_path": "/Hermes/private/reports"}],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(binary, "batch", str(plan_path), "--json", "--dry-run")

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"]["items"][0]["result"]["dry_run"] is True
    assert not (tmp_path / "rclone.jsonl").exists()
