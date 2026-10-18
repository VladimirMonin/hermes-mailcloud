"""Win32 alias spellings must be rejected before lock or journal side effects."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.name != "nt":
    pytest.skip("native Windows alias regression", allow_module_level=True)

from hermes_mailcloud._platform import journal_windows as backend  # noqa: E402
from hermes_mailcloud.journal import JournalError, LinkJournal  # noqa: E402
from hermes_mailcloud.rclone.parser import PublicLink  # noqa: E402

_TESTS_ROOT = next(parent for parent in Path(__file__).resolve().parents if parent.name == "tests")
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import isolated_environment  # noqa: E402

WORKER = _TESTS_ROOT / "helpers" / "journal_worker.py"
PUBLIC_URL = "https://cloud.mail.ru/public/coder-correction/alias-regression"


def _journal_path(root: Path) -> Path:
    return root / "managed-private" / "links.jsonl"


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _identity(path: Path) -> tuple[int, int, int]:
    handle = backend._open_handle(
        path, backend.win32con.GENERIC_READ | backend.win32con.READ_CONTROL
    )
    try:
        information = backend.win32file.GetFileInformationByHandle(handle)
        return (information[4], information[8], information[9])
    finally:
        backend.win32file.CloseHandle(handle)


def _record_with_worker(root: Path, path: Path, suffix: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKER), "record", str(path), suffix, PUBLIC_URL],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        env=isolated_environment(root),
    )


@pytest.mark.parametrize("suffix", [".", " ", ":stream"])
def test_win32_alias_spellings_are_rejected_before_side_effects(
    tmp_path: Path, suffix: str
) -> None:
    root = tmp_path / f"alias-{ord(suffix[-1])}"
    path = _journal_path(root)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    alias = path.with_name(path.name + suffix)
    if suffix != ":stream":
        assert _identity(alias) == _identity(path)

    with pytest.raises(JournalError) as caught:
        LinkJournal(alias).prepare()
    assert "unsupported link or alias" in str(caught.value)

    with backend.exclusive_lock(_lock_path(path), timeout_seconds=0.5):
        completed = _record_with_worker(root, alias, "alias-child")
    assert completed.returncode == 3
    payload = json.loads(completed.stdout)
    assert payload["success"] is False
    assert "unsupported link or alias" in payload["message"]
    assert len(path.read_bytes().splitlines()) == 1
    assert sorted(p.name for p in path.parent.glob("*.lock")) == [".links.jsonl.lock"]
    assert list(path.parent.glob(".*.tmp")) == []


def _short_path(path: Path) -> Path:
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        pytest.skip("8.3 short names are unavailable on this volume")
    short = Path(buffer.value)
    if str(short).casefold() == str(path).casefold():
        pytest.skip("8.3 short names are disabled for this path")
    return short


def test_windows_8_3_short_name_alias_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "long-directory-name"
    path = root / "private-state" / "long-journal-name.jsonl"
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    short = _short_path(path)
    assert _identity(short) == _identity(path)

    with pytest.raises(JournalError) as caught:
        LinkJournal(short).prepare()
    assert "unsupported link or alias" in str(caught.value)
    assert sorted(p.name for p in path.parent.glob("*.lock")) == [".long-journal-name.jsonl.lock"]


def test_normal_path_contention_control_and_successful_append(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))

    with backend.exclusive_lock(_lock_path(path), timeout_seconds=0.5):
        blocked = _record_with_worker(tmp_path, path, "blocked")
    assert blocked.returncode == 3
    assert json.loads(blocked.stdout)["success"] is False
    assert "timed out" in json.loads(blocked.stdout)["message"]
    assert len(path.read_bytes().splitlines()) == 1

    completed = _record_with_worker(tmp_path, path, "normal")
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["success"] is True
    assert len(path.read_bytes().splitlines()) == 2
    assert sorted(p.name for p in path.parent.glob("*.lock")) == [".links.jsonl.lock"]
    assert list(path.parent.glob(".*.tmp")) == []
