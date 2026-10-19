"""Explicit, pinned, user-scoped rclone preparation; ordinary lookup is read-only.

Only Windows/Linux amd64 are supported. No package-install hooks, cloud setup,
user configuration writes, PATH changes, selfupdate or ordinary-command network.
Owner-private storage reuses the accepted platform primitives without changing
journal behavior. Like those primitives, this is not protection against the same
user, administrators or SYSTEM. A private activation receipt retains the verified
hash of an installed generation; newer package pins do not silently update it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import ssl
import stat
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath

from .._platform import PrivateStorageError, backend
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from .runner import RcloneRunner, RcloneRunnerError, _resolve_windows_executable

MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 4096
_ALLOWED_HOST = "downloads.rclone.org"
_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    system: str
    architecture: str
    url: str
    archive_sha256: str
    archive_bytes: int
    executable_sha256: str
    executable_bytes: int
    member: str

    @property
    def executable_name(self) -> str:
        return "rclone.exe" if self.system == "windows" else "rclone"

    @property
    def directory_name(self) -> str:
        return _generation(self.version, self.system, self.architecture, self.executable_sha256)


def _error(kind: ErrorKind, message: str) -> MailCloudError:
    return MailCloudError(ErrorPayload(kind, message))


def _target() -> tuple[str, str]:
    system = {"win32": "windows", "linux": "linux"}.get(sys.platform)
    if (
        system is None
        or platform.machine().casefold() not in {"amd64", "x86_64"}
        or struct.calcsize("P") != 8
    ):
        raise _error(
            ErrorKind.BACKEND_UNSUPPORTED, "setup supports 64-bit Windows/Linux amd64 only"
        )
    if system == "windows" and sys.getwindowsversion().major < 10:
        raise _error(
            ErrorKind.BACKEND_UNSUPPORTED, "setup requires Windows 10 / Server 2016 or newer"
        )
    if system == "linux":
        kernel = re.match(r"([0-9]+)\.([0-9]+)", platform.release())
        if kernel is None or tuple(map(int, kernel.groups())) < (3, 2):
            raise _error(ErrorKind.BACKEND_UNSUPPORTED, "setup requires Linux kernel 3.2 or newer")
    return system, "amd64"


def pinned_release() -> Release:
    system, architecture = _target()
    try:
        raw = files(__package__).joinpath("releases.json").read_bytes()
        if len(raw) > 64 * 1024:
            raise ValueError
        manifest = json.loads(raw)
        if manifest["schema_version"] != 1 or not _VERSION.fullmatch(manifest["version"]):
            raise ValueError
        matches = [
            item
            for item in manifest["releases"]
            if item["system"] == system
            and item["architecture"] == architecture
            and item["version"] == manifest["version"]
        ]
        if len(matches) != 1:
            raise ValueError
        release = Release(**matches[0])
        _validate_release(release)
        return release
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise _error(
            ErrorKind.CONFIG_ERROR, "the packaged rclone release manifest is invalid"
        ) from exc


def _validate_release(release: Release) -> None:
    _validate_url(release.url)
    root = f"rclone-{release.version}-{release.system}-{release.architecture}"
    if (
        not _VERSION.fullmatch(release.version)
        or release.system not in {"windows", "linux"}
        or release.architecture != "amd64"
        or not _SHA256.fullmatch(release.archive_sha256)
        or not _SHA256.fullmatch(release.executable_sha256)
        or type(release.archive_bytes) is not int
        or not 0 < release.archive_bytes <= MAX_ARCHIVE_BYTES
        or type(release.executable_bytes) is not int
        or not 0 < release.executable_bytes <= MAX_EXECUTABLE_BYTES
        or release.member != root + "/" + release.executable_name
        or release.url != f"https://{_ALLOWED_HOST}/{release.version}/{root}.zip"
    ):
        raise _error(ErrorKind.CONFIG_ERROR, "the packaged rclone release manifest is invalid")


def managed_data_root(environment: Mapping[str, str] | None = None) -> Path:
    """Dedicated per-user data, never site-packages or the user's config directory."""
    env = os.environ if environment is None else environment
    if sys.platform == "win32":
        value = env.get("LOCALAPPDATA")
        if value is None:
            home = env.get("USERPROFILE") or env.get("HOME")
            value = str(Path(home) / "AppData" / "Local") if home else None
    else:
        value = env.get("XDG_DATA_HOME")
        if value is None:
            home = env.get("HOME")
            value = str((Path(home) if home else Path.home()) / ".local" / "share")
    if not value or not Path(value).is_absolute():
        raise _error(ErrorKind.CONFIG_ERROR, "setup requires an absolute per-user data directory")
    return Path(value) / "hermes-mailcloud" / "rclone"


def _generation(version: str, system: str, architecture: str, digest: str) -> str:
    return f"{version}-{system}-{architecture}-{digest[:16]}"


def _active(root: Path) -> tuple[Path, dict] | None:
    """Trust only owner-private receipt bytes and revalidate the whole binary hash.

    The receipt contains no URL or arbitrary path. It is written only after a
    pinned archive and native version have been verified. Keeping its pinned hash
    lets a working older managed generation survive a later package manifest.
    """
    storage = backend()
    raw = storage.read_private_bytes(root / "active.json", max_bytes=MAX_RECEIPT_BYTES)
    if not raw:
        return None
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != {
        "schema_version",
        "version",
        "system",
        "architecture",
        "sha256",
        "bytes",
    }:
        return None
    system, architecture = _target()
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or record["system"] != system
        or record["architecture"] != architecture
        or not isinstance(record["version"], str)
        or not _VERSION.fullmatch(record["version"])
        or not isinstance(record["sha256"], str)
        or not _SHA256.fullmatch(record["sha256"])
        or type(record["bytes"]) is not int
        or not 0 < record["bytes"] <= MAX_EXECUTABLE_BYTES
    ):
        return None
    directory = _generation(record["version"], system, architecture, record["sha256"])
    path = root / "releases" / directory / ("rclone.exe" if system == "windows" else "rclone")
    content = storage.read_private_bytes(path, max_bytes=record["bytes"])
    if len(content) != record["bytes"] or hashlib.sha256(content).hexdigest() != record["sha256"]:
        return None
    if os.name == "posix" and not path.stat().st_mode & stat.S_IXUSR:
        return None
    return path, record


def managed_rclone_path(environment: Mapping[str, str] | None = None) -> Path | None:
    """Read-only, no-network fallback; never create or repair storage implicitly."""
    try:
        active = _active(managed_data_root(environment))
        return active[0] if active is not None else None
    except (MailCloudError, PrivateStorageError, OSError, ValueError, UnicodeError):
        return None


def external_rclone_path(binary: str, environment: Mapping[str, str]) -> str | None:
    if os.name == "nt":
        try:
            return _resolve_windows_executable(binary, environment)
        except RcloneRunnerError as exc:
            if exc.error.kind is ErrorKind.RCLONE_NOT_FOUND:
                return None
            raise
    return shutil.which(binary, path=environment.get("PATH", os.defpath))


def _validate_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == _ALLOWED_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path.startswith("/")
        )
    except ValueError:
        valid = False
    if not valid:
        raise _error(
            ErrorKind.CONFIG_ERROR, "rclone download route is not an allowed official HTTPS URL"
        )


class _OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def _open_download(url: str, *, timeout_seconds: float):
    _validate_url(url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _OfficialRedirects(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "hermes-mailcloud-setup/1", "Accept-Encoding": "identity"}
    )
    return opener.open(request, timeout=timeout_seconds)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _error(ErrorKind.TIMEOUT, "rclone setup timed out; no automatic retry was attempted")
    return remaining


def _acquire_archive(release: Release, archive: Path | None, deadline: float) -> bytes:
    try:
        if archive is None:
            stream = _open_download(release.url, timeout_seconds=min(15, _remaining(deadline)))
        else:
            information = archive.lstat()
            if not stat.S_ISREG(information.st_mode) or (
                getattr(information, "st_file_attributes", 0) & 0x400
            ):
                raise _error(
                    ErrorKind.PARSE_ERROR, "the supplied rclone archive is not a regular file"
                )
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(archive, flags)
            stream = os.fdopen(descriptor, "rb")
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                information.st_dev,
                information.st_ino,
            ):
                stream.close()
                raise _error(
                    ErrorKind.PARSE_ERROR, "the supplied rclone archive changed while opening"
                )
        with stream:
            if archive is None:
                _validate_url(stream.geturl())
                if (
                    stream.status != 200
                    or stream.headers.get("Content-Encoding", "identity") != "identity"
                ):
                    raise _error(
                        ErrorKind.NETWORK_ERROR,
                        "the official rclone download was not a complete archive",
                    )
                length = stream.headers.get("Content-Length")
                if length is not None and int(length) != release.archive_bytes:
                    raise _error(ErrorKind.PARSE_ERROR, "the rclone archive has an unexpected size")
            content = bytearray()
            while True:
                _remaining(deadline)
                block = stream.read1(65536)
                if not block:
                    break
                content.extend(block)
                if len(content) > release.archive_bytes or len(content) > MAX_ARCHIVE_BYTES:
                    raise _error(
                        ErrorKind.PARSE_ERROR, "the rclone archive exceeds its pinned size"
                    )
        if (
            len(content) != release.archive_bytes
            or hashlib.sha256(content).hexdigest() != release.archive_sha256
        ):
            raise _error(
                ErrorKind.PARSE_ERROR,
                "the rclone archive did not match its pinned SHA-256 and size",
            )
        return bytes(content)
    except MailCloudError:
        raise
    except FileNotFoundError as exc:
        raise _error(ErrorKind.NOT_FOUND, "the supplied rclone archive was not found") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise _error(
            ErrorKind.NETWORK_ERROR, "rclone could not be acquired; retry hermes-mailcloud setup"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise _error(
            ErrorKind.PARSE_ERROR, "the rclone download has invalid archive metadata"
        ) from exc


def _extract_executable(content: bytes, release: Release, deadline: float) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= 32:
                raise ValueError
            expected_root = release.member.split("/", 1)[0]
            selected = []
            for member in members:
                name = member.filename.rstrip("/")
                parts = name.split("/")
                kind = stat.S_IFMT(member.external_attr >> 16)
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or ":" in name
                    or PurePosixPath(name).is_absolute()
                    or any(part in {"", ".", ".."} for part in parts)
                    or parts[0] != expected_root
                    or member.flag_bits & 1
                    or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                ):
                    raise ValueError
                if member.filename == release.member:
                    selected.append(member)
            if (
                len(selected) != 1
                or selected[0].is_dir()
                or selected[0].file_size != release.executable_bytes
            ):
                raise ValueError
            result = bytearray()
            with archive.open(selected[0]) as source:
                while block := source.read(65536):
                    _remaining(deadline)
                    result.extend(block)
                    if len(result) > release.executable_bytes:
                        raise ValueError
            if (
                len(result) != release.executable_bytes
                or hashlib.sha256(result).hexdigest() != release.executable_sha256
            ):
                raise ValueError
            return bytes(result)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise _error(
            ErrorKind.PARSE_ERROR,
            "the verified rclone archive does not contain its expected executable",
        ) from exc


def _verify_executable(
    path: Path,
    *,
    expected_version: str | None,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> str:
    # rclone rejects reserved Windows NUL as --config. Use a genuine fresh,
    # owner-private empty file; never inspect the user's cloud configuration.
    try:
        with tempfile.TemporaryDirectory(prefix="hermes-rclone-check-") as temporary:
            probe = Path(temporary) / "private"
            storage = backend()
            storage.ensure_private_directory(probe)
            config = probe / "empty.conf"
            storage.atomic_write_replace(config, b"", max_bytes=1)
            source = {key: environment[key] for key in ("PATH", "SystemRoot") if key in environment}
            source.update(HOME=str(probe), RCLONE_CONFIG=str(config))
            result = RcloneRunner(str(path), environment=source, max_capture_bytes=4096).run(
                (
                    "--config",
                    str(config),
                    "--cache-dir",
                    str(probe / "cache"),
                    "--temp-dir",
                    str(probe),
                    "version",
                ),
                timeout_seconds=min(10, timeout_seconds),
            )
    except (PrivateStorageError, OSError) as exc:
        raise _error(
            ErrorKind.CONFIG_ERROR,
            "the isolated rclone version check could not be prepared or cleaned safely",
        ) from exc
    line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    match = re.fullmatch(r"rclone (v[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+_-]*)", line)
    if (
        result.returncode
        or result.stdout_truncated
        or match is None
        or (expected_version is not None and match[1] != expected_version)
    ):
        raise _error(
            ErrorKind.PARSE_ERROR, "the rclone executable did not pass its safe version check"
        )
    return match[1]


def _activate(root: Path, stage: Path, release: Release) -> None:
    storage = backend()
    directory = root / "releases" / release.directory_name
    storage.ensure_private_directory(directory)
    destination = directory / release.executable_name
    storage.assert_private_regular_file(destination, allow_missing=True)
    os.replace(stage, destination)
    storage.assert_private_regular_file(destination, allow_missing=False)
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    record = {
        "schema_version": 1,
        "version": release.version,
        "system": release.system,
        "architecture": release.architecture,
        "sha256": release.executable_sha256,
        "bytes": release.executable_bytes,
    }
    storage.atomic_write_replace(
        root / "active.json",
        json.dumps(record, sort_keys=True).encode("utf-8"),
        max_bytes=MAX_RECEIPT_BYTES,
    )


def _result(status: str, source: str, version: str | None) -> dict[str, object]:
    return {
        "dependency": "rclone",
        "status": status,
        "source": source,
        "version": version,
        "cloud_configured": False,
    }


def prepare_rclone(
    binary: str = "rclone",
    *,
    explicit: bool = False,
    environment: Mapping[str, str] | None = None,
    archive: Path | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 60,
) -> dict[str, object]:
    """Prepare only a missing dependency; never replace an explicit/external rclone."""
    env = os.environ if environment is None else environment
    release = pinned_release()
    if dry_run:
        return _result(
            "dry_run", "external" if explicit else "managed", None if explicit else release.version
        )
    deadline = time.monotonic() + min(90, max(0.001, timeout_seconds))
    external = external_rclone_path(binary if explicit else "rclone", env)
    if external is not None:
        version = _verify_executable(
            Path(external),
            expected_version=None,
            environment=env,
            timeout_seconds=_remaining(deadline),
        )
        return _result("already_available", "external", version)
    if explicit:
        raise _error(
            ErrorKind.RCLONE_NOT_FOUND,
            "the explicit rclone executable was not found; setup did not replace it",
        )
    root = managed_data_root(env)
    storage = backend()
    stage = root / (".stage-" + uuid.uuid4().hex + "-" + release.executable_name)
    stage_owned = False
    try:
        storage.ensure_private_directory(root)
        with storage.exclusive_lock(
            root / ".setup.lock", timeout_seconds=min(5, _remaining(deadline))
        ):
            storage.assert_private_regular_file(root / "active.json", allow_missing=True)
            active = managed_rclone_path(env)
            if active is not None:
                record = _active(root)[1]
                return _result("already_available", "managed", record["version"])
            if stage.exists() or stage.is_symlink():
                raise _error(
                    ErrorKind.CONFLICT, "the private setup staging name is already occupied"
                )
            content = _acquire_archive(release, archive, deadline)
            executable = _extract_executable(content, release, deadline)
            stage_owned = True
            storage.atomic_write_replace(stage, executable, max_bytes=MAX_EXECUTABLE_BYTES)
            if os.name == "posix":
                os.chmod(stage, 0o700, follow_symlinks=False)
            storage.assert_private_regular_file(stage, allow_missing=False)
            del content, executable
            staged_bytes = storage.read_private_bytes(stage, max_bytes=release.executable_bytes)
            if (
                len(staged_bytes) != release.executable_bytes
                or hashlib.sha256(staged_bytes).hexdigest() != release.executable_sha256
            ):
                raise _error(
                    ErrorKind.PARSE_ERROR, "the staged rclone executable changed before execution"
                )
            del staged_bytes
            _verify_executable(
                stage,
                expected_version=release.version,
                environment=env,
                timeout_seconds=_remaining(deadline),
            )
            _remaining(deadline)
            _activate(root, stage, release)
            return _result("installed", "managed", release.version)
    except MailCloudError:
        raise
    except (PrivateStorageError, OSError) as exc:
        raise _error(
            ErrorKind.CONFIG_ERROR,
            "managed rclone could not be activated safely; previous release files were retained",
        ) from exc
    finally:
        if stage_owned:
            try:
                stage.unlink(missing_ok=True)
            except OSError as exc:
                raise _error(
                    ErrorKind.UNKNOWN_ERROR, "rclone setup staging cleanup could not be confirmed"
                ) from exc
