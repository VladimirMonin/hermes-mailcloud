"""Tests for private, atomic local public-link journal records."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink

PUBLIC_URL = "https://cloud.mail.ru/public/test-capability/path"


def _journal_path(root: Path) -> Path:
    """Use a missing leaf directory so the journal creates its own private storage."""
    return root / "private-state" / "links.jsonl"


def _payloads(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def test_journal_creates_private_directory_and_atomically_appends_complete_records(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)

    first = journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    second = journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert _payloads(path) == [first.to_payload(), second.to_payload()]
    assert _lock_path(path).is_file()
    assert list(path.parent.glob(".*.tmp")) == []
    LinkJournal(path).prepare()


def test_journal_leaves_the_previous_file_untouched_if_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    original = path.read_bytes()

    if os.name == "nt":
        from hermes_mailcloud._platform import journal_windows as backend

        replace = backend._replace_file

        def fail_replace(source: str, destination: str) -> None:
            if Path(destination) == path:
                raise OSError("simulated replace failure")
            replace(source, destination)

        monkeypatch.setattr(backend, "_replace_file", fail_replace)
    else:
        from hermes_mailcloud._platform import journal_posix as backend

        replace = os.replace

        def fail_replace(
            source: str | os.PathLike[str], destination: str | os.PathLike[str]
        ) -> None:
            if Path(destination) == path:
                raise OSError("simulated replace failure")
            replace(source, destination)

        monkeypatch.setattr(backend.os, "replace", fail_replace)

    with pytest.raises(JournalError) as caught:
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert "test-capability" not in str(caught.value)
    assert path.read_bytes() == original
    assert list(path.parent.glob(".*.tmp")) == []


def test_prepare_uses_the_existing_private_lock_and_reads_the_journal_before_return(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    original = path.read_bytes()

    LinkJournal(path).prepare()

    assert _lock_path(path).is_file()
    assert path.read_bytes() == original


def test_prepare_rejects_an_oversized_existing_journal_before_recording(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    path.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_record_rejects_an_append_that_would_exceed_the_limit_without_truncation(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    existing = path.read_bytes()
    path.write_bytes(existing + b"x" * (MAX_JOURNAL_BYTES - len(existing)))
    padded = path.read_bytes()
    assert len(padded) == MAX_JOURNAL_BYTES

    with pytest.raises(JournalError):
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert path.read_bytes() == padded
    assert list(path.parent.glob(".*.tmp")) == []


def test_record_accepts_a_utf8_record_that_reaches_exactly_the_limit(tmp_path: Path) -> None:
    seed_path = _journal_path(tmp_path / "seed")
    seed = LinkJournal(seed_path)
    seed.record("publish", "/Hermes/public/юникод.txt", PublicLink(PUBLIC_URL))
    line_length = len(seed_path.read_bytes())

    path = _journal_path(tmp_path / "boundary")
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/юникод.txt", PublicLink(PUBLIC_URL))
    prefix = b"x" * (MAX_JOURNAL_BYTES - line_length - 1) + b"\n"
    path.write_bytes(prefix)

    journal.record("publish", "/Hermes/public/юникод.txt", PublicLink(PUBLIC_URL))

    assert path.stat().st_size == MAX_JOURNAL_BYTES
    assert path.read_bytes().endswith(b"\n")


def test_record_rejects_invalid_operation_and_link_objects(tmp_path: Path) -> None:
    journal = LinkJournal(_journal_path(tmp_path))

    with pytest.raises(ValueError):
        journal.record("remove", "/Hermes/public/file.txt", PublicLink(PUBLIC_URL))
    with pytest.raises(ValueError):
        journal.record("link", "/Hermes/public/file.txt", "not-a-public-link")  # type: ignore[arg-type]


def test_prepare_maps_unreadable_storage_to_a_safe_journal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    original = path.read_bytes()

    def deny_read(*_args: object, **_kwargs: object) -> bytes:
        raise journal_module.PrivateStorageError("local link journal could not be read safely")

    monkeypatch.setattr(journal_module, "_read_private_journal", deny_read)

    with pytest.raises(JournalError) as caught:
        LinkJournal(path).prepare()

    assert "test-capability" not in str(caught.value)
    assert str(caught.value) == "local link journal could not be read safely"
    assert path.read_bytes() == original
