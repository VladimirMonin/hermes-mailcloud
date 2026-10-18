"""POSIX-specific owner, mode, link and durability guarantees for the journal."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

if os.name != "posix":
    pytest.skip("POSIX journal guarantees", allow_module_level=True)

import hermes_mailcloud.journal as journal_module  # noqa: E402
from hermes_mailcloud._platform import PrivateStorageError  # noqa: E402
from hermes_mailcloud._platform import journal_posix as backend  # noqa: E402
from hermes_mailcloud.journal import JournalError, LinkJournal  # noqa: E402
from hermes_mailcloud.rclone.parser import PublicLink  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX journal guarantees")

PUBLIC_URL = "https://cloud.mail.ru/public/posix-capability/path"


def _journal_path(root: Path) -> Path:
    return root / "private-state" / "links.jsonl"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def test_posix_private_modes_survive_a_permissive_umask(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    previous = os.umask(0)
    try:
        LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    finally:
        os.umask(previous)

    assert _mode(path.parent) == 0o700
    assert _mode(path) == 0o600
    assert _mode(_lock_path(path)) == 0o600


def test_posix_existing_trusted_0755_parent_is_allowed_and_not_chmodded(tmp_path: Path) -> None:
    parent = tmp_path / "trusted"
    parent.mkdir()
    parent.chmod(0o755)
    path = parent / "links.jsonl"

    LinkJournal(path).prepare()

    assert _mode(parent) == 0o755
    assert _mode(_lock_path(path)) == 0o600


def test_posix_unsafe_owner_less_writable_parent_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "unsafe"
    parent.mkdir()
    parent.chmod(0o777)

    with pytest.raises(JournalError):
        LinkJournal(parent / "links.jsonl").prepare()


def test_posix_symlinked_journal_or_lock_is_rejected(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    target = tmp_path / "target.bin"
    target.write_bytes(b"not-a-journal")

    path.unlink()
    path.symlink_to(target)
    with pytest.raises(JournalError):
        LinkJournal(path).prepare()

    path.unlink()
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    lock = _lock_path(path)
    lock.unlink()
    lock.symlink_to(target)
    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_posix_symlinked_parent_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-parent"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(JournalError):
        LinkJournal(link / "links.jsonl").prepare()


def test_posix_hardlinked_journal_is_rejected(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    os.link(path, tmp_path / "journal-hardlink")

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_posix_hardlinked_lock_is_rejected(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    os.link(_lock_path(path), tmp_path / "lock-hardlink")

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_posix_file_owner_check_rejects_another_uid_without_privilege(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    information = path.stat()
    monkeypatch.setattr(backend, "_current_uid", lambda: information.st_uid + 1)

    with pytest.raises(PrivateStorageError):
        backend._assert_private_file_stat(information)


def test_posix_foreign_owner_is_rejected_by_real_chown_when_privileged(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        pytest.skip("changing a real owner requires root; the UID check is covered separately")
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    os.chown(path, 65534, 65534)

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_posix_file_fsync_failure_before_replace_keeps_old_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    original = path.read_bytes()
    monkeypatch.setattr(journal_module, "_probe_private_storage", lambda _parent: None)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(backend.os, "fsync", fail_fsync)

    with pytest.raises(JournalError):
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    assert path.read_bytes() == original
    assert list(path.parent.glob(".*.tmp")) == []


def test_posix_directory_fsync_failure_after_replace_leaves_the_new_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    monkeypatch.setattr(journal_module, "_probe_private_storage", lambda _parent: None)

    def fail_directory_fsync(_path: Path) -> None:
        raise PrivateStorageError("could not securely update the local link journal")

    monkeypatch.setattr(backend, "_fsync_directory", fail_directory_fsync)

    with pytest.raises(JournalError):
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert PUBLIC_URL + "-second" in lines[1]
