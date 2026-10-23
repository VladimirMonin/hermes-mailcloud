"""Composed vertical tests for the portable child-CLI fake harness."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import (  # noqa: E402
    PUBLIC_URL,
    CliFakeHarness,
    isolated_environment,
)


def _write_plan(
    path: Path, operations: list[dict[str, object]], *, continue_on_error: bool
) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "defaults": {"continue_on_error": continue_on_error},
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_harness_public_batch_creates_a_real_private_journal_after_preflight(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "local files" / "report [1] & ü.txt"
    source.parent.mkdir()
    source.write_text("public", encoding="utf-8")
    remote_path = "/Hermes/public/отчёт [1] & done.txt"
    plan = _write_plan(
        tmp_path / "public-plan.json",
        [
            {"op": "mkdir", "remote_path": "/Hermes/private/before-public"},
            {"op": "publish", "local_path": str(source), "remote_path": remote_path},
            {"op": "link", "remote_path": remote_path},
        ],
        continue_on_error=False,
    )

    result = harness.run(
        "batch",
        str(plan),
        "--json",
        "--yes",
        responses={"link": {"stdout": f"{PUBLIC_URL}\n"}},
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert PUBLIC_URL not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "completed"
    assert payload["result"]["succeeded"] == 3
    records = [
        json.loads(line) for line in harness.journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["operation"] for record in records] == ["publish", "link"]
    assert all(record["public_url"] == PUBLIC_URL for record in records)
    assert [call[0] for call in harness.recorded_calls()] == [
        "mkdir",
        "copyto",
        "link",
        "link",
    ]
    assert harness.recorded_calls()[1] == [
        "copyto",
        str(source),
        f"fake:{remote_path}",
        "--immutable",
    ]


def test_harness_post_backend_journal_failure_is_honest_and_not_retried(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    remote_path = "/Hermes/public/report.txt"

    result = harness.run(
        "publish",
        str(source),
        remote_path,
        "--yes",
        "--json",
        responses={"link": {"stdout": f"{PUBLIC_URL}\n"}},
        sabotage={
            "command": "link",
            "mode": "broaden-lock",
            "journal": str(harness.journal),
        },
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "unknown_error"
    assert "remote effect may have occurred" in payload["error"]["message"]
    assert "will not be retried" in payload["error"]["message"]
    combined = result.stdout + result.stderr
    assert PUBLIC_URL not in combined
    assert str(harness.journal.parent) not in combined
    assert "cli-harness-capability" not in combined
    assert [call[0] for call in harness.recorded_calls()] == ["copyto", "link"]
    assert not harness.journal.exists()


@pytest.mark.parametrize("continue_on_error", [False, True])
def test_harness_batch_post_backend_journal_failure_keeps_stop_continue_and_exit_11(
    tmp_path: Path, continue_on_error: bool
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    remote_path = "/Hermes/public/report.txt"
    plan = _write_plan(
        tmp_path / "partial-plan.json",
        [
            {"op": "publish", "local_path": str(source), "remote_path": remote_path},
            {"op": "mkdir", "remote_path": "/Hermes/private/after-public"},
        ],
        continue_on_error=continue_on_error,
    )

    result = harness.run(
        "batch",
        str(plan),
        "--json",
        "--yes",
        responses={"link": {"stdout": f"{PUBLIC_URL}\n"}},
        sabotage={
            "command": "link",
            "mode": "broaden-lock",
            "journal": str(harness.journal),
        },
    )

    assert result.returncode == 11
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "partial_failure"
    assert payload["result"]["exit_code"] == 11
    assert payload["result"]["failed"] == 1
    assert payload["result"]["total"] == (2 if continue_on_error else 1)
    assert "remote effect may have occurred" in payload["result"]["items"][0]["error"]["message"]
    calls = [call[0] for call in harness.recorded_calls()]
    assert calls == (["copyto", "link", "mkdir"] if continue_on_error else ["copyto", "link"])


def test_harness_dry_run_creates_no_journal_lock_temp_or_backend_call(tmp_path: Path) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")

    result = harness.run(
        "publish",
        str(source),
        "/Hermes/public/report.txt",
        "--dry-run",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["published"] is False
    assert not harness.journal.parent.exists()
    assert harness.recorded_calls() == []
    assert not harness.journal.with_name(f".{harness.journal.name}.lock").exists()


def test_harness_batch_dry_run_with_public_operations_creates_no_journal(tmp_path: Path) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    plan = _write_plan(
        tmp_path / "dry-run-public.json",
        [
            {"op": "publish", "local_path": str(source), "remote_path": "/Hermes/public/r.txt"},
            {"op": "link", "remote_path": "/Hermes/public/r.txt"},
        ],
        continue_on_error=False,
    )

    result = harness.run("batch", str(plan), "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    assert not harness.journal.parent.exists()
    assert not harness.journal.with_name(f".{harness.journal.name}.lock").exists()
    assert harness.recorded_calls() == []


def test_isolated_environment_is_explicit_and_secret_free(tmp_path: Path) -> None:
    environment = isolated_environment(tmp_path)

    expected = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "TMPDIR",
        "RCLONE_CONFIG",
        "PYTHONDONTWRITEBYTECODE",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "PYTHONPATH",
    }
    if os.name == "nt":
        expected.add("SystemRoot")
    assert set(environment) == expected
    assert not any(
        key.startswith("HMC_") or (key.startswith("RCLONE_") and key != "RCLONE_CONFIG")
        for key in environment
    )
    assert Path(environment["RCLONE_CONFIG"]).is_relative_to(tmp_path)
    assert Path(environment["RCLONE_CONFIG"]).read_bytes() == b""
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "HTTP_PROXY" not in environment
    for key in (
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "TMPDIR",
        "PATH",
    ):
        assert environment[key].startswith(str(tmp_path))
