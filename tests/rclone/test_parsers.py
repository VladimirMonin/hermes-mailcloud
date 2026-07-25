"""Golden parser tests for rclone lsjson and public-link output."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.rclone.parser import RcloneParseError, parse_lsjson, parse_public_link

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_lsjson_normalizes_stable_items_from_a_golden_fixture() -> None:
    stdout = (FIXTURES / "lsjson-success.json").read_text(encoding="utf-8")

    assert parse_lsjson(stdout, root="/Hermes") == [
        {"name": "private", "path": "/Hermes/private", "type": "directory"},
        {
            "modified": "2026-07-25T01:02:03Z",
            "name": "notes.txt",
            "path": "/Hermes/private/notes.txt",
            "size": 17,
            "type": "file",
        },
    ]


def test_parse_lsjson_rejects_malformed_json_without_echoing_raw_stdout() -> None:
    with pytest.raises(RcloneParseError) as caught:
        parse_lsjson("{not-valid-json", root="/Hermes")

    assert caught.value.error.kind is ErrorKind.PARSE_ERROR
    assert "not-valid-json" not in caught.value.error.message


@pytest.mark.parametrize(
    "payload",
    [
        '[{"Path": "../escape", "Name": "escape", "IsDir": false, "Size": 1}]',
        '[{"Path": "file.txt", "Name": "file.txt", "IsDir": false, "Size": -1}]',
        '{"Path": "not-an-array"}',
    ],
)
def test_parse_lsjson_rejects_invalid_item_shapes(payload: str) -> None:
    with pytest.raises(RcloneParseError):
        parse_lsjson(payload, root="/Hermes")


def test_parse_public_link_returns_private_url_with_a_safe_fingerprint() -> None:
    stdout = (FIXTURES / "link-success.txt").read_text(encoding="utf-8")

    link = parse_public_link(stdout)

    assert link.url == "https://cloud.mail.ru/public/capability-token/path"
    assert link.fingerprint.startswith("sha256:")
    assert len(link.fingerprint) == len("sha256:") + 64


@pytest.mark.parametrize(
    "stdout",
    [
        "https://example.test/public/capability",
        "http://cloud.mail.ru/public/capability",
        "no URL returned",
    ],
)
def test_parse_public_link_rejects_non_allowlisted_or_missing_urls(stdout: str) -> None:
    with pytest.raises(RcloneParseError) as caught:
        parse_public_link(stdout)

    assert caught.value.error.kind is ErrorKind.PARSE_ERROR


@pytest.mark.parametrize(
    "stdout",
    [
        "https://cloud.mail.ru/public/../private",
        "https://cloud.mail.ru/public/%2e%2e/private",
    ],
)
def test_parse_public_link_rejects_dot_segment_traversal_after_normalization(stdout: str) -> None:
    with pytest.raises(RcloneParseError) as caught:
        parse_public_link(stdout)

    assert caught.value.error.kind is ErrorKind.PARSE_ERROR
