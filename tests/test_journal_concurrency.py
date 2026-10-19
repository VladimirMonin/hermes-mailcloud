"""Spawn-compatible multi-process journal locking and atomic-visibility tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud.journal import JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink

_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import isolated_environment  # noqa: E402

WORKER = Path(__file__).resolve().parent / "helpers" / "journal_worker.py"
PUBLIC_URL = "https://cloud.mail.ru/public/concurrency-capability"


def _journal_path(root: Path) -> Path:
    return root / "private-state" / "links.jsonl"


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _worker_environment(root: Path) -> dict[str, str]:
    return isolated_environment(root)


def _start_worker(root: Path, *arguments: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(WORKER), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_worker_environment(root),
    )


def _wait_for_marker(marker: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            break
        time.sleep(0.02)
    _stderr = process.stderr.read() if process.stderr is not None else b""
    raise AssertionError(f"worker did not acquire the lock: {_stderr!r}")


def _lock_identity(path: Path) -> tuple[int, ...]:
    if os.name == "nt":
        import win32con
        import win32file

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
        return (information[4], information[8], information[9])
    information = path.stat()
    return (information.st_dev, information.st_ino)


def test_separate_processes_append_without_lost_updates_or_mixed_records(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    processes = [
        _start_worker(tmp_path, "append", str(path), f"writer-{index}", "5", PUBLIC_URL)
        for index in range(4)
    ]
    for process in processes:
        _stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr.decode("utf-8", errors="replace")

    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 20
    assert len({record["public_url"] for record in records}) == 20
    assert all(record["version"] == 1 for record in records)
    LinkJournal(path).prepare()


def test_concurrent_readers_see_only_nonempty_complete_old_or_new_versions(
    tmp_path: Path,
) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    seed = path.read_bytes()
    reader_done = threading.Event()
    snapshots: list[bytes] = []
    failures: list[tuple[str, str]] = []

    def read_while_writing() -> None:
        while not reader_done.is_set():
            try:
                snapshot = journal_module._read_private_journal(path)
            except Exception as exc:
                failures.append((type(exc).__name__, str(exc)))
            else:
                if snapshot:
                    snapshots.append(snapshot)
                else:
                    failures.append(("empty_after_seed", ""))
            time.sleep(0.001)

    readers = [threading.Thread(target=read_while_writing, daemon=True) for _ in range(2)]
    for reader in readers:
        reader.start()
    process = _start_worker(tmp_path, "append", str(path), "reader", "100", PUBLIC_URL)
    try:
        _stdout, stderr = process.communicate(timeout=40)
        assert process.returncode == 0, stderr.decode("utf-8", errors="replace")
    finally:
        reader_done.set()
        for reader in readers:
            reader.join(timeout=5)

    final = path.read_bytes()
    assert len(final.splitlines()) == 101
    assert final.startswith(seed)
    assert not failures, failures[:5]
    assert all(not reader.is_alive() for reader in readers)
    assert snapshots
    invalid: list[bytes] = []
    for snapshot in snapshots:
        if not snapshot.endswith(b"\n") or not snapshot.startswith(seed):
            invalid.append(snapshot)
            continue
        if not final.startswith(snapshot):
            invalid.append(snapshot)
            continue
        for line in snapshot.splitlines():
            json.loads(line)
    assert not invalid


@pytest.mark.skipif(os.name != "nt", reason="native Windows replacement handles")
@pytest.mark.parametrize("replacement", ["private", "hardlink", "broad_dacl"])
def test_reader_revalidates_a_generation_replaced_after_open(
    tmp_path: Path, monkeypatch, replacement: str
) -> None:
    from helpers.journal_worker import broaden_capability
    from hermes_mailcloud._platform import journal_windows as backend

    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    seed = path.read_bytes()
    opened = threading.Event()
    resume = threading.Event()
    snapshots: list[bytes] = []
    failures: list[Exception] = []
    opened_ids: list[tuple[int, ...]] = []
    closed_ids: list[tuple[int, ...]] = []
    after_replace: list[tuple[int, int]] = []
    reads: list[int] = []
    original_open = backend._open_handle
    original_close = backend.win32file.CloseHandle
    original_read = backend.win32file.ReadFile

    def identity(handle) -> tuple[int, ...]:
        info = backend.win32file.GetFileInformationByHandle(handle)
        return (info[4], info[8], info[9])

    def pause_after_open(file_path, *args, **kwargs):
        handle = original_open(file_path, *args, **kwargs)
        if threading.current_thread() is reader and Path(file_path) == path:
            opened_ids.append(identity(handle))
            if len(opened_ids) == 1:
                try:
                    backend._assert_private_file_handle(handle)
                    opened.set()
                    assert resume.wait(10)
                    info = backend.win32file.GetFileInformationByHandle(handle)
                    after_replace.append((info[0], info[7]))
                except BaseException:
                    original_close(handle)
                    raise
        return handle

    def track_close(handle):
        if threading.current_thread() is reader:
            try:
                file_id = identity(handle)
            except backend.pywintypes.error:
                pass  # Token handles are not disk-file handles.
            else:
                if file_id in opened_ids:
                    closed_ids.append(file_id)
        return original_close(handle)

    def track_read(handle, *args, **kwargs):
        if threading.current_thread() is reader:
            reads.append(1)
        return original_read(handle, *args, **kwargs)

    def read_once() -> None:
        try:
            snapshots.append(journal_module._read_private_journal(path))
        except Exception as exc:
            failures.append(exc)

    reader = threading.Thread(target=read_once)
    monkeypatch.setattr(backend, "_open_handle", pause_after_open)
    monkeypatch.setattr(backend.win32file, "CloseHandle", track_close)
    monkeypatch.setattr(backend.win32file, "ReadFile", track_read)
    reader.start()
    try:
        assert opened.wait(10)
        LinkJournal(path).record("publish", "/Hermes/public/next.txt", PublicLink(PUBLIC_URL))
        final = path.read_bytes()
        assert final.startswith(seed) and len(final.splitlines()) == 2
        if replacement == "hardlink":
            os.link(path, path.with_name("second-link.jsonl"))
        elif replacement == "broad_dacl":
            broaden_capability(path)
    finally:
        resume.set()
        reader.join(10)

    assert not reader.is_alive()
    assert len(after_replace) == 1 and after_replace[0][1] == 0
    assert not after_replace[0][0] & (
        backend.win32con.FILE_ATTRIBUTE_DIRECTORY | backend.win32con.FILE_ATTRIBUTE_REPARSE_POINT
    )
    assert len(opened_ids) == 2 and opened_ids[0] != opened_ids[1]
    assert closed_ids == opened_ids
    if replacement == "private":
        assert not failures
        assert snapshots == [final] and reads
    else:
        assert len(failures) == 1 and isinstance(failures[0], JournalError)
        assert not snapshots and not reads
        if replacement == "broad_dacl":
            assert "DACL" in str(failures[0])


def test_lock_is_released_when_a_holder_exits_or_crashes(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    LinkJournal(path).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))

    marker = tmp_path / "normal-holder.marker"
    normal = _start_worker(tmp_path, "hold", str(path), str(marker), "0.2")
    _wait_for_marker(marker, normal)
    _stdout, stderr = normal.communicate(timeout=10)
    assert normal.returncode == 0, stderr.decode("utf-8", errors="replace")
    LinkJournal(path).record(
        "publish", "/Hermes/public/after-normal.txt", PublicLink(PUBLIC_URL + "/after")
    )

    crash_marker = tmp_path / "crash-holder.marker"
    crash = _start_worker(tmp_path, "crash", str(path), str(crash_marker))
    _wait_for_marker(crash_marker, crash)
    crash.wait(timeout=10)
    assert crash.returncode == 9
    LinkJournal(path).record(
        "publish", "/Hermes/public/after-crash.txt", PublicLink(PUBLIC_URL + "/crash")
    )


def test_lock_contention_is_bounded_and_recovers_after_the_holder_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
    marker = tmp_path / "contention.marker"
    holder = _start_worker(tmp_path, "hold", str(path), str(marker), "5.0")
    try:
        _wait_for_marker(marker, holder)
        monkeypatch.setattr(journal_module, "LOCK_ACQUIRE_TIMEOUT_SECONDS", 0.2)
        started = time.monotonic()
        with pytest.raises(JournalError) as caught:
            journal.record(
                "publish",
                "/Hermes/public/contended.txt",
                PublicLink(PUBLIC_URL + "/contended"),
            )
        assert time.monotonic() - started < 1.5
        assert "timed out" in str(caught.value)
    finally:
        if holder.poll() is None:
            holder.terminate()
        holder.wait(timeout=10)

    monkeypatch.setattr(journal_module, "LOCK_ACQUIRE_TIMEOUT_SECONDS", 5.0)
    journal.record("publish", "/Hermes/public/recovered.txt", PublicLink(PUBLIC_URL + "/recovered"))


def test_lock_sidecar_identity_is_stable_across_records(tmp_path: Path) -> None:
    path = _journal_path(tmp_path)
    journal = LinkJournal(path)
    journal.record("publish", "/Hermes/public/first.txt", PublicLink(PUBLIC_URL))
    first_identity = _lock_identity(_lock_path(path))

    journal.record("link", "/Hermes/public/second.txt", PublicLink(PUBLIC_URL + "/second"))

    assert _lock_identity(_lock_path(path)) == first_identity
