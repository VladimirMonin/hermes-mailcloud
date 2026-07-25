"""Strict parsers for rclone's untrusted lsjson and link output."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.paths import RemotePathError, normalize_remote_path, require_descendant

PUBLIC_LINK_PREFIX = "https://cloud.mail.ru/public/"


class RcloneParseError(MailCloudError):
    """A stable parse failure that never includes raw provider output."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorPayload(ErrorKind.PARSE_ERROR, message))


@dataclass(frozen=True, slots=True)
class PublicLink:
    """Owner-private public capability and its safe non-reversible fingerprint."""

    url: str

    @property
    def fingerprint(self) -> str:
        return f"sha256:{hashlib.sha256(self.url.encode('utf-8')).hexdigest()}"


def parse_lsjson(stdout: str, *, root: str) -> list[dict[str, object]]:
    """Convert one lsjson array into sorted, path-safe stable listing items."""
    try:
        normalized_root = normalize_remote_path(root)
    except RemotePathError as exc:
        raise RcloneParseError("listing root was invalid") from exc
    try:
        decoded = json.loads(stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RcloneParseError("rclone lsjson output was malformed") from exc
    if not isinstance(decoded, list):
        raise RcloneParseError("rclone lsjson output must be an array")

    items = [_parse_lsjson_item(item, root=normalized_root) for item in decoded]
    paths = [str(item["path"]) for item in items]
    if len(paths) != len(set(paths)):
        raise RcloneParseError("rclone lsjson output contains duplicate paths")
    return sorted(items, key=lambda item: str(item["path"]))


def parse_public_link(stdout: str) -> PublicLink:
    """Extract exactly one allowlisted HTTPS Mail.ru public capability URL."""
    candidates = [token for token in stdout.split() if token.startswith(PUBLIC_LINK_PREFIX)]
    if len(candidates) != 1:
        raise RcloneParseError("rclone link did not return one allowed public URL")
    url = candidates[0]
    try:
        parsed = urlsplit(url)
        normalized_path = posixpath.normpath(unquote(parsed.path))
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == "cloud.mail.ru"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and normalized_path.startswith("/public/")
        )
    except ValueError as exc:
        raise RcloneParseError("rclone link did not return one allowed public URL") from exc
    if not valid:
        raise RcloneParseError("rclone link did not return one allowed public URL")
    return PublicLink(url=url)


def _parse_lsjson_item(raw: object, *, root: str) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise RcloneParseError("rclone lsjson output contains a non-object item")
    relative_path = raw.get("Path")
    name = raw.get("Name")
    is_directory = raw.get("IsDir")
    if not isinstance(relative_path, str) or not _is_safe_relative_path(relative_path):
        raise RcloneParseError("rclone lsjson item path was invalid")
    if not isinstance(name, str) or not name:
        raise RcloneParseError("rclone lsjson item name was invalid")
    if not isinstance(is_directory, bool):
        raise RcloneParseError("rclone lsjson item directory flag was invalid")

    try:
        path = require_descendant(normalize_remote_path(posixpath.join(root, relative_path)), root)
    except RemotePathError as exc:
        raise RcloneParseError("rclone lsjson item escaped the requested root") from exc

    item: dict[str, object] = {
        "path": path,
        "name": name,
        "type": "directory" if is_directory else "file",
    }
    modified = raw.get("ModTime")
    if modified is not None:
        if not isinstance(modified, str) or not modified:
            raise RcloneParseError("rclone lsjson item modification time was invalid")
        if not is_directory:
            item["modified"] = modified
    if not is_directory:
        size = raw.get("Size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RcloneParseError("rclone lsjson item file size was invalid")
        item["size"] = size
    return item


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\x00" in value or value.startswith("/") or value.endswith("/"):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)
