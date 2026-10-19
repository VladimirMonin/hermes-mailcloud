"""Native Windows owner, protected-DACL, reparse and storage checks for the journal."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

if os.name != "nt":
    pytest.skip("native Windows journal guarantees", allow_module_level=True)

import hermes_mailcloud.journal as journal_module  # noqa: E402
from hermes_mailcloud._platform import PrivateStorageError  # noqa: E402
from hermes_mailcloud._platform import journal_windows as backend  # noqa: E402
from hermes_mailcloud.journal import JournalError, LinkJournal  # noqa: E402
from hermes_mailcloud.rclone.parser import PublicLink  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows journal guarantees")

if os.name == "nt":
    import subprocess

    import win32api
    import win32con
    import win32file
    import win32security

PUBLIC_URL = "https://cloud.mail.ru/public/windows-capability/path"


def _journal_path(root: Path) -> Path:
    return root / "private-state" / "links.jsonl"


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _current_user_sid() -> object:
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32file.CloseHandle(token)


def _dacl_signature(path: Path) -> tuple[object, ...]:
    descriptor = win32security.GetFileSecurity(
        str(path),
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    owner = win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
    control = descriptor.GetSecurityDescriptorControl()[0]
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        return (owner, control, None)
    aces = tuple(
        (
            dacl.GetAce(index)[0],
            dacl.GetAce(index)[1],
            win32security.ConvertSidToStringSid(dacl.GetAce(index)[2]),
        )
        for index in range(dacl.GetAceCount())
    )
    return (owner, control, aces)


def _set_null_dacl(path: Path) -> None:
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, None, False)
    win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, descriptor)


def _set_everyone_dacl(path: Path) -> None:
    everyone = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32file.FILE_ALL_ACCESS, everyone)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, descriptor)


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("creating a junction is unavailable in this environment")


def test_windows_private_directory_journal_and_lock_have_protected_owner_dacls(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))

    expected_owner = win32security.ConvertSidToStringSid(_current_user_sid())
    allowed = {
        expected_owner,
        win32security.ConvertSidToStringSid(backend._system_sid()),
        win32security.ConvertSidToStringSid(backend._administrators_sid()),
    }
    for capability_path in (path.parent, path, _lock_path(path)):
        owner, control, aces = _dacl_signature(capability_path)
        assert owner == expected_owner
        assert control & win32security.SE_DACL_PROTECTED
        assert aces
        assert all(ace[2] in allowed for ace in aces)
        assert any(ace[2] == expected_owner for ace in aces)
        if capability_path.is_dir():
            backend._assert_private_directory(capability_path)
        else:
            backend.assert_private_regular_file(capability_path, allow_missing=False)

    handle = win32file.CreateFile(
        str(path),
        win32con.READ_CONTROL,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL | win32file.FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    try:
        information = win32file.GetFileInformationByHandle(handle)
    finally:
        win32file.CloseHandle(handle)
    assert information[7] == 1
    assert list(path.parent.glob(".*.tmp")) == []


def test_windows_plain_inherited_directory_is_rejected_and_positive_control_passes(
    tmp_path: Path,
) -> None:
    inherited = tmp_path / "plain"
    inherited.mkdir()
    with pytest.raises(JournalError):
        LinkJournal(inherited / "links.jsonl").prepare()

    private = _journal_path(tmp_path)
    LinkJournal(private).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    LinkJournal(private).prepare()


def test_windows_null_or_broad_dacl_is_rejected_after_a_positive_control(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    _set_null_dacl(_lock_path(path))
    with pytest.raises(JournalError):
        LinkJournal(path).prepare()

    other = _journal_path(tmp_path / "other")
    LinkJournal(other).record("publish", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL))
    _set_everyone_dacl(other)
    with pytest.raises(JournalError):
        LinkJournal(other).prepare()


def test_windows_temporary_capability_file_is_private_and_removed(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).prepare()
    temporary, handle = backend._create_temporary(path.parent, "probe")
    expected_owner = win32security.ConvertSidToStringSid(_current_user_sid())
    try:
        backend._assert_private_file_handle(handle)
        owner, control, aces = _dacl_signature(temporary)
        assert owner == expected_owner
        assert control & win32security.SE_DACL_PROTECTED
        assert aces
    finally:
        win32file.CloseHandle(handle)
        backend._delete_quietly(temporary)
    assert not temporary.exists()


@pytest.mark.parametrize("scenario", ["slow_first_open", "retired_again", "missing", "broad_dacl"])
def test_windows_retired_generation_retry_is_bounded_and_revalidates_privacy(
    tmp_path: Path, monkeypatch, scenario: str
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    seed = path.read_bytes()
    clock = [0.0]
    sleeps: list[float] = []
    opened: list[tuple[int, ...]] = []
    closed: list[tuple[int, ...]] = []
    reads: list[int] = []
    nested = False
    original_open = backend._open_handle
    original_close = win32file.CloseHandle
    original_read = win32file.ReadFile

    def identity(handle) -> tuple[int, ...]:
        info = win32file.GetFileInformationByHandle(handle)
        return (info[4], info[8], info[9])

    def retire_before_validation(file_path, *args, **kwargs):
        nonlocal nested
        handle = original_open(file_path, *args, **kwargs)
        if Path(file_path) == path and not nested:
            opened.append(identity(handle))
            if len(opened) == 1 or scenario == "retired_again":
                try:
                    nested = True
                    LinkJournal(path).record(
                        "publish", "/Hermes/public/replacement.txt", PublicLink(PUBLIC_URL)
                    )
                    assert win32file.GetFileInformationByHandle(handle)[7] == 0
                    if scenario == "missing":
                        path.unlink()
                    elif scenario == "broad_dacl":
                        _set_null_dacl(path)
                    clock[0] += 0.06 if scenario == "slow_first_open" else 0.03
                except BaseException:
                    original_close(handle)
                    raise
                finally:
                    nested = False
        return handle

    def track_close(handle):
        if not nested:
            try:
                file_id = identity(handle)
            except backend.pywintypes.error:
                pass
            else:
                if file_id in opened:
                    closed.append(file_id)
        return original_close(handle)

    def track_read(handle, *args, **kwargs):
        if not nested:
            reads.append(1)
        return original_read(handle, *args, **kwargs)

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(backend, "_open_handle", retire_before_validation)
    monkeypatch.setattr(win32file, "CloseHandle", track_close)
    monkeypatch.setattr(win32file, "ReadFile", track_read)
    if scenario == "slow_first_open":
        snapshot = journal_module._read_private_journal(path)
        assert snapshot == path.read_bytes() and snapshot.startswith(seed)
        assert len(snapshot.splitlines()) == 2 and reads
        assert len(opened) == 2 and not sleeps
    else:
        with pytest.raises(JournalError) as caught:
            journal_module._read_private_journal(path)
        assert not reads
        if scenario == "broad_dacl":
            assert "DACL" in str(caught.value) and len(opened) == 2 and not sleeps
        else:
            assert str(caught.value) == "local link journal could not be read safely"
            assert len(opened) == (2 if scenario == "retired_again" else 1)
            assert clock[0] <= 0.06
    assert closed == opened


def test_windows_persistent_sharing_violation_is_not_hidden(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    handle = win32file.CreateFile(
        str(path),
        win32con.GENERIC_READ,
        0,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    try:
        started = time.monotonic()
        with pytest.raises(PrivateStorageError) as caught:
            backend.read_private_bytes(path, max_bytes=1024)
        assert time.monotonic() - started < 1.0
        assert "could not be read safely" in str(caught.value)
    finally:
        win32file.CloseHandle(handle)
    assert backend.read_private_bytes(path, max_bytes=1024) == path.read_bytes()


def test_windows_directory_flush_failure_after_replace_leaves_the_new_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    monkeypatch.setattr(journal_module, "_probe_private_storage", lambda _parent: None)

    def fail_directory_flush(_path: Path) -> None:
        raise PrivateStorageError("could not securely update the local link journal")

    monkeypatch.setattr(backend, "_flush_directory", fail_directory_flush)

    with pytest.raises(JournalError):
        journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "-second"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert PUBLIC_URL + "-second" in lines[1]
    assert list(path.parent.glob(".*.tmp")) == []
    backend.assert_private_regular_file(path, allow_missing=False)


def test_windows_junction_alias_is_rejected_before_side_effects(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "junction"
    _make_junction(junction, target)

    with pytest.raises(JournalError):
        LinkJournal(junction / "links.jsonl").prepare()


def test_windows_symlinked_journal_is_rejected_when_available(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    target = path.parent / "target.bin"
    target.write_bytes(b"not-a-journal")
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("creating a file symlink requires an unavailable Windows privilege")

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_windows_relative_unc_and_device_paths_are_rejected() -> None:
    for path in (
        Path("links.jsonl"),
        Path(r"\\server\share\links.jsonl"),
        Path(r"\\.\C:\links.jsonl"),
    ):
        with pytest.raises(JournalError):
            LinkJournal(path).prepare()


def test_windows_unsupported_storage_is_rejected_at_the_system_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)

    monkeypatch.setattr(backend.win32file, "GetDriveType", lambda _root: win32con.DRIVE_REMOTE)
    with pytest.raises(JournalError):
        LinkJournal(path).prepare()

    monkeypatch.setattr(backend.win32file, "GetDriveType", lambda _root: win32con.DRIVE_FIXED)
    monkeypatch.setattr(
        backend.win32api,
        "GetVolumeInformation",
        lambda _root: ("volume", 0, 255, 0, "FAT32"),
    )
    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_windows_hardlinked_journal_is_rejected(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    os.link(path, tmp_path / "journal-hardlink")

    with pytest.raises(JournalError):
        LinkJournal(path).prepare()


def test_windows_owner_sid_check_rejects_a_simulated_foreign_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    handle = win32file.CreateFile(
        str(path),
        win32con.READ_CONTROL,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL | win32file.FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    try:
        monkeypatch.setattr(backend, "_current_user_sid", backend._system_sid)
        with pytest.raises(PrivateStorageError):
            backend._assert_private_file_handle(handle)
    finally:
        win32file.CloseHandle(handle)


def test_windows_failed_prepare_does_not_modify_an_existing_foreign_directory(
    tmp_path: Path,
) -> None:
    inherited = tmp_path / "foreign"
    inherited.mkdir()
    before = _dacl_signature(inherited)

    with pytest.raises(JournalError):
        LinkJournal(inherited / "links.jsonl").prepare()

    assert _dacl_signature(inherited) == before
