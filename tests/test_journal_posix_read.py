"""POSIX production read path must not hide persistent capability-file errors."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

if os.name != "posix":
    pytest.skip("POSIX journal read regression", allow_module_level=True)

import hermes_mailcloud.journal as journal_module  # noqa: E402
from hermes_mailcloud.journal import JournalError, LinkJournal  # noqa: E402
from hermes_mailcloud.rclone.parser import PublicLink  # noqa: E402

PUBLIC_URL = "https://cloud.mail.ru/public/coder-correction/posix-read"


def test_posix_common_read_does_not_hide_a_persistent_hardlink_error(tmp_path: Path) -> None:
    path = tmp_path / "private-state" / "links.jsonl"
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    os.link(path, tmp_path / "read-hardlink")

    with pytest.raises(JournalError):
        journal_module._read_private_journal(path)
