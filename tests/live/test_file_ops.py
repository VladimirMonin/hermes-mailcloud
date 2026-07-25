"""Opt-in end-to-end CLI evidence for isolated Mail.ru file operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_mailcloud.probes.core import resolve_test_root

pytestmark = pytest.mark.live


def _isolated_live_root() -> str:
    """Generate or validate the only root this test suite may mutate."""
    if os.environ.get("HMC_LIVE") != "1":
        pytest.skip("set HMC_LIVE=1 to run live Mail.ru file operations")
    return resolve_test_root(os.environ.get("HMC_TEST_ROOT"))


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=90,
        env=os.environ.copy(),
    )


def _json_payload(result: subprocess.CompletedProcess[str], operation: str) -> dict[str, object]:
    assert result.stderr == "", f"{operation} must not emit a raw backend diagnostic"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"{operation} did not return a JSON envelope") from error
    assert isinstance(payload, dict)
    return payload


def _require_success(operation: str, *arguments: str) -> dict[str, object]:
    result = _run_cli(*arguments, "--json")
    payload = _json_payload(result, operation)
    assert result.returncode == 0, f"{operation} did not succeed"
    assert payload.get("ok") is True
    assert payload.get("operation") == operation
    return payload


def _require_root_absent(root: str) -> None:
    result = _run_cli("ls", root, "--json")
    payload = _json_payload(result, "ls")
    if result.returncode == 0:
        pytest.fail("refusing to mutate because the isolated live root already exists")
    error = payload.get("error")
    if not isinstance(error, dict) or error.get("kind") != "not_found":
        pytest.fail("could not establish that the isolated live root is absent")


def _verify_root_removed(root: str) -> None:
    result = _run_cli("ls", root, "--json")
    payload = _json_payload(result, "ls")
    assert result.returncode == 7, "same-run recursive cleanup did not remove the isolated root"
    error = payload.get("error")
    assert isinstance(error, dict) and error.get("kind") == "not_found"


def test_cli_file_operations_live_in_one_isolated_root(tmp_path: Path) -> None:
    """Exercise every implemented file command and verify same-run cleanup by read-back."""
    root = _isolated_live_root()
    source = tmp_path / "source.txt"
    download_target = tmp_path / "downloaded.txt"
    source_bytes = b"hermes-mailcloud live file suite\n"
    source.write_bytes(source_bytes)
    remote_source = f"{root}/source.txt"
    remote_moved = f"{root}/moved.txt"
    remote_copied = f"{root}/copied.txt"
    root_created = False

    _require_root_absent(root)
    try:
        _require_success("mkdir", "mkdir", root)
        root_created = True

        uploaded = _require_success("upload", "upload", str(source), remote_source)
        assert uploaded["result"] == {
            "local_path": str(source),
            "remote_path": remote_source,
            "published": False,
            "bytes": len(source_bytes),
            "overwrite": "never",
        }
        listed = _require_success("ls", "ls", root)
        listing = listed.get("result")
        assert isinstance(listing, dict)
        source_items = [
            item
            for item in listing.get("items", [])
            if isinstance(item, dict) and item.get("path") == remote_source
        ]
        assert len(source_items) == 1
        assert source_items[0]["name"] == "source.txt"
        assert source_items[0]["size"] == len(source_bytes)
        assert source_items[0]["type"] == "file"
        inspected = _require_success("stat", "stat", remote_source)
        inspected_result = inspected.get("result")
        assert isinstance(inspected_result, dict)
        assert inspected_result["remote_path"] == remote_source
        assert inspected_result["size"] == len(source_bytes)
        assert inspected_result["type"] == "file"

        downloaded = _require_success("download", "download", remote_source, str(download_target))
        assert downloaded["result"] == {
            "remote_path": remote_source,
            "local_path": str(download_target),
            "overwrite": "never",
            "bytes": len(source_bytes),
            "updated": True,
        }
        assert download_target.read_bytes() == source_bytes

        moved = _require_success("mv", "mv", remote_source, remote_moved)
        assert moved["result"] == {
            "source_path": remote_source,
            "target_path": remote_moved,
            "overwrite": "never",
        }
        copied = _require_success("cp", "cp", remote_moved, remote_copied)
        assert copied["result"] == {
            "source_path": remote_moved,
            "target_path": remote_copied,
            "overwrite": "never",
        }
        deleted_file = _require_success("rm", "rm", remote_copied, "--yes")
        assert deleted_file["result"] == {
            "remote_path": remote_copied,
            "recursive": False,
            "deleted": True,
        }
        deleted_root = _require_success("rm", "rm", root, "--recursive", "--yes")
        assert deleted_root["result"] == {"remote_path": root, "recursive": True, "deleted": True}
        root_created = False
        _verify_root_removed(root)
    finally:
        if root_created:
            cleanup = _run_cli("rm", root, "--recursive", "--yes", "--json")
            cleanup_payload = _json_payload(cleanup, "rm")
            assert cleanup.returncode == 0 and cleanup_payload.get("ok") is True, (
                "same-run cleanup command failed"
            )
            _verify_root_removed(root)
