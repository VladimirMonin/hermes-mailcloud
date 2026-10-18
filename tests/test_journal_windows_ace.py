"""Native object ACE must become a safe JournalError and JSON error envelope."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

if os.name != "nt":
    pytest.skip("native Windows ACL regression", allow_module_level=True)

import pywintypes  # noqa: E402
import win32security  # noqa: E402

from hermes_mailcloud._platform import journal_windows as backend  # noqa: E402
from hermes_mailcloud.journal import JournalError, LinkJournal  # noqa: E402
from hermes_mailcloud.rclone.parser import PublicLink  # noqa: E402

_TESTS_ROOT = next(parent for parent in Path(__file__).resolve().parents if parent.name == "tests")
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import CliFakeHarness  # noqa: E402

PUBLIC_URL = "https://cloud.mail.ru/public/coder-correction/object-ace"


def _install_object_ace(path: Path) -> None:
    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = descriptor.GetSecurityDescriptorDacl()
    dacl.AddAccessAllowedObjectAce(
        win32security.ACL_REVISION_DS,
        0,
        0x0001,
        pywintypes.IID("{11111111-1111-1111-1111-111111111111}"),
        None,
        backend._current_user_sid(),
    )
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    win32security.SetFileSecurity(
        str(path),
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        descriptor,
    )


def test_native_object_ace_is_rejected_as_a_safe_typed_error(tmp_path: Path) -> None:
    harness = CliFakeHarness.create(tmp_path)
    path = harness.journal
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    LinkJournal(path).prepare()

    _install_object_ace(path)
    installed = win32security.GetFileSecurity(
        str(path), win32security.DACL_SECURITY_INFORMATION
    ).GetSecurityDescriptorDacl()
    assert installed is not None
    assert installed.GetAceCount() >= 4
    assert 5 in [len(installed.GetAce(index)) for index in range(installed.GetAceCount())]
    assert 5 in [installed.GetAce(index)[0][0] for index in range(installed.GetAceCount())]

    with pytest.raises(JournalError) as caught:
        LinkJournal(path).prepare()
    assert PUBLIC_URL not in str(caught.value)
    assert str(path.parent) not in str(caught.value)

    result = harness.run("link", "/Hermes/public/seed.txt", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "unknown_error"
    assert "ValueError" not in result.stderr
    combined = result.stdout + result.stderr
    assert PUBLIC_URL not in combined
    assert str(path.parent) not in combined
    assert harness.recorded_calls() == []
