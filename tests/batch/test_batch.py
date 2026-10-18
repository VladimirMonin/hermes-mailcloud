"""Schema-conformant fake/golden tests for deterministic v0.1 batch execution."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud._platform import PrivateStorageError
from hermes_mailcloud.batch import BatchCommands, BatchPlan, parse_batch_document, parse_batch_file
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload, MailCloudError
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunnerError

_TESTS_ROOT = next(parent for parent in Path(__file__).resolve().parents if parent.name == "tests")
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import CliFakeHarness  # noqa: E402
from helpers.journal_worker import broaden_capability, make_reparse_link  # noqa: E402

FIXTURES = Path(__file__).with_name("fixtures")
PUBLIC_URL = "https://cloud.mail.ru/public/batch-capability/path"


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


def _journal_path(root: Path) -> Path:
    return root / "private-state" / "links.jsonl"


def _lock_path(journal: Path) -> Path:
    return journal.with_name(f".{journal.name}.lock")


def _prepare_private_journal(journal: Path) -> None:
    LinkJournal(journal).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))


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
    if failure == "unreadable_journal":
        _prepare_private_journal(journal)

        def deny_read(*_args: object, **_kwargs: object) -> bytes:
            raise PrivateStorageError("local link journal could not be read safely")

        monkeypatch.setattr(journal_module, "_read_private_journal", deny_read)
        return

    _prepare_private_journal(journal)

    if failure == "insecure_lock":
        broaden_capability(_lock_path(journal))
        return
    if failure == "symlink_lock":
        lock = _lock_path(journal)
        lock.unlink()
        target = journal.parent / "link-target"
        target.mkdir()
        try:
            make_reparse_link(lock, target)
        except OSError:
            pytest.skip("creating a test reparse link is unavailable in this environment")
        return
    if failure == "invalid_permission_journal":
        broaden_capability(journal)
        return
    if failure == "oversized_journal":
        journal.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))
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
    journal = _journal_path(tmp_path)
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


@pytest.mark.parametrize("continue_on_error", [False, True])
def test_public_batch_backend_success_then_journal_failure_keeps_partial_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, continue_on_error: bool
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = _journal_path(tmp_path)
    outcomes = [
        RcloneResult(0, "", "", 1),
        RcloneResult(0, f"{PUBLIC_URL}\n", "", 1),
    ]
    if continue_on_error:
        outcomes.append(RcloneResult(0, "", "", 1))
    backend = RecordingBackend(outcomes)
    plan = _plan(
        {
            "op": "publish",
            "local_path": str(source),
            "remote_path": "/Hermes/public/report.txt",
        },
        {"op": "mkdir", "remote_path": "/Hermes/private/after-public"},
        continue_on_error=continue_on_error,
    )

    def fail_replace(_path: Path, _content: bytes) -> None:
        raise JournalError("simulated local record failure")

    monkeypatch.setattr(journal_module, "_atomic_replace", fail_replace)

    execution = _commands(backend, journal=journal).run(plan, dry_run=False, yes=True)

    assert execution.result["status"] == "partial_failure"
    assert execution.result["exit_code"] == 11
    assert execution.result["total"] == (2 if continue_on_error else 1)
    assert execution.result["failed"] == 1
    first = execution.result["items"][0]
    assert first["ok"] is False
    assert first["error"]["kind"] == "unknown_error"
    assert "remote effect may have occurred" in first["error"]["message"]
    assert "will not be retried" in first["error"]["message"]
    assert PUBLIC_URL not in json.dumps(execution.result)
    assert str(journal.parent) not in json.dumps(execution.result)
    assert [call[0][0] for call in backend.calls] == (
        ["copyto", "link", "mkdir"] if continue_on_error else ["copyto", "link"]
    )


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


def test_cli_executes_the_validated_plan_and_emits_a_golden_completed_envelope(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
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

    result = harness.run("batch", str(plan_path), "--json", "--yes")

    assert result.returncode == 0, result.stderr
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
    assert harness.recorded_calls() == [["mkdir", "fake:/Hermes/private/reports"]]


def test_cli_partial_failure_exits_11_and_never_leaks_fake_backend_diagnostics(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
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
    responses = {
        json.dumps(["mkdir", "fake:/Hermes/private/failed"]): {
            "stderr": "network is unreachable batch-backend-sentinel\n",
            "returncode": 1,
        }
    }

    result = harness.run("batch", str(plan_path), "--json", "--yes", responses=responses)

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
    harness = CliFakeHarness.create(tmp_path)
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

    result = harness.run("batch", str(plan_path), "--json", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"]["items"][0]["result"]["dry_run"] is True
    assert harness.recorded_calls() == []
