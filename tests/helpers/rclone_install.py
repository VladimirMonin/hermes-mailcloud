"""Synthetic installer fixtures only; never discover a user's rclone/config/home."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from pathlib import Path


def environment(root: Path) -> dict[str, str]:
    paths = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "LOCALAPPDATA": root / "appdata",
        "APPDATA": root / "appdata",
        "TEMP": root / "temp",
        "TMP": root / "temp",
        "TMPDIR": root / "temp",
        "PATH": root / "empty-path",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    result = {key: str(value) for key, value in paths.items()}
    config = root / "config.toml"
    config.write_text("[profiles.default]\n", encoding="utf-8")
    empty = root / "empty-rclone.conf"
    empty.write_bytes(b"")
    result.update(HMC_CONFIG=str(config), RCLONE_CONFIG=str(empty), PYTHONUTF8="1")
    if os.name == "nt":
        result["SystemRoot"] = os.environ["SystemRoot"]
    return result


def archive_fixture(system: str, *, version: str = "v1.75.2", extra=None):
    executable = b"synthetic native executable; never run this fixture\n"
    member = f"rclone-{version}-{system}-amd64/" + (
        "rclone.exe" if system == "windows" else "rclone"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        information = zipfile.ZipInfo(member)
        information.create_system = 3
        information.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(information, executable)
        if extra is not None:
            archive.writestr(*extra)
    payload = stream.getvalue()
    specification = {
        "version": version,
        "system": system,
        "architecture": "amd64",
        "url": f"https://downloads.rclone.org/{version}/rclone-{version}-{system}-amd64.zip",
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "archive_bytes": len(payload),
        "executable_sha256": hashlib.sha256(executable).hexdigest(),
        "executable_bytes": len(executable),
        "member": member,
    }
    return payload, specification, executable
