"""Spawn-compatible helper that exercises the real journal in a separate process."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from hermes_mailcloud import _platform
from hermes_mailcloud import journal as journal_module
from hermes_mailcloud.journal import JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(2)
    mode, *arguments = argv
    if mode == "append":
        journal_path, prefix, count, url_base = arguments
        journal = LinkJournal(Path(journal_path))
        for index in range(int(count)):
            journal.record(
                "publish",
                f"/Hermes/public/{prefix}-{index}.txt",
                PublicLink(f"{url_base}/{prefix}/{index}"),
            )
        return 0
    if mode == "record":
        journal_path, suffix, url = arguments
        journal_module.LOCK_ACQUIRE_TIMEOUT_SECONDS = 0.2
        try:
            LinkJournal(Path(journal_path)).record(
                "link", f"/Hermes/public/{suffix}.txt", PublicLink(url)
            )
        except JournalError as exc:
            print(json.dumps({"success": False, "message": str(exc)}))
            return 3
        print(json.dumps({"success": True}))
        return 0
    if mode == "hold":
        journal_path, marker, seconds = arguments
        with _lock(Path(journal_path)):
            Path(marker).write_text("locked", encoding="ascii")
            time.sleep(float(seconds))
        return 0
    if mode == "crash":
        journal_path, marker = arguments
        with _lock(Path(journal_path)):
            Path(marker).write_text("locked", encoding="ascii")
            os._exit(9)
    if mode == "broaden":
        broaden_capability(Path(arguments[0]))
        return 0
    if mode == "prepare":
        LinkJournal(Path(arguments[0])).prepare()
        return 0
    raise SystemExit(2)


def _lock(journal_path: Path):
    lock_path = journal_path.with_name(f".{journal_path.name}.lock")
    return _platform.backend().exclusive_lock(lock_path, timeout_seconds=5)


def broaden_capability(path: Path) -> None:
    """Corrupt exactly one capability object's local protection for a negative test."""
    if os.name == "nt":
        import win32security

        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorDacl(True, None, False)
        win32security.SetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION, descriptor
        )
        return
    path.chmod(0o644)


def make_reparse_link(link: Path, target: Path) -> None:
    """Create a test-only directory symlink or junction for a no-follow negative test."""
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise OSError("test junction could not be created")
        return
    link.symlink_to(target, target_is_directory=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
