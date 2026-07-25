"""Tests for private, atomic local public-link journal records."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink

PUBLIC_URL = "https://cloud.mail.ru/public/test-capability/path"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_journal_creates_private_directory_and_atomically_appends_complete_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "links.jsonl"
    journal = LinkJournal(path)

    first = journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    second = journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert _mode(path.parent) == 0o700
    assert _mode(path) == 0o600
    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert payloads == [first.to_payload(), second.to_payload()]
    assert all(
        payload["public_url"].startswith("https://cloud.mail.ru/public/") for payload in payloads
    )
    assert list(path.parent.glob(".*.tmp")) == []


def test_journal_leaves_the_previous_file_untouched_if_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "links.jsonl"
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    original = path.read_bytes()

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(journal_module.os, "replace", fail_replace)

    with pytest.raises(JournalError) as caught:
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert "test-capability" not in str(caught.value)
    assert path.read_bytes() == original
    assert list(path.parent.glob(".*.tmp")) == []


def test_journal_rejects_insecure_existing_file_without_exposing_private_contents(
    tmp_path: Path,
) -> None:
    path = tmp_path / "links.jsonl"
    path.write_text('{"public_url":"private-capability-sentinel"}\n', encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(JournalError) as caught:
        LinkJournal(path).record("link", "/Hermes/public/report.txt", PublicLink(PUBLIC_URL))

    assert "private-capability-sentinel" not in str(caught.value)
    assert path.read_text(encoding="utf-8") == '{"public_url":"private-capability-sentinel"}\n'


def test_prepare_creates_a_private_lock_and_reads_existing_journal_before_return(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "links.jsonl"
    path.parent.mkdir(mode=0o700)
    path.write_bytes(b'{"version":1}\n')
    path.chmod(0o600)

    LinkJournal(path).prepare()

    lock_path = path.with_name(f".{path.name}.lock")
    assert _mode(lock_path) == 0o600


def test_prepare_rejects_an_oversized_existing_journal_before_recording(tmp_path: Path) -> None:
    path = tmp_path / "links.jsonl"
    path.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))
    path.chmod(0o600)

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()
