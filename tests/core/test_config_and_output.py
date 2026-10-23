"""Tests for strict secret-free configuration and output redaction."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from hermes_mailcloud.config import (
    CliConfigOverrides,
    ConfigError,
    ConfigOverrides,
    ResolvedConfig,
    resolve_config,
)
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload
from hermes_mailcloud.core.result import ResultEnvelope
from hermes_mailcloud.output import redact_text, render_json, sanitize_value


def test_config_overrides_preserves_the_legacy_alias() -> None:
    assert CliConfigOverrides is ConfigOverrides
    assert CliConfigOverrides() == ConfigOverrides(profile=None, remote=None, config_path=None)


def test_cli_remote_overrides_environment_then_profile_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[profiles.default]
remote = "profile:"
rclone_path = "profile-rclone"
links_journal = "~/profile-links.jsonl"
timeout_seconds = 120
""".strip(),
        encoding="utf-8",
    )
    environment = {
        "HMC_REMOTE": "environment:",
        "HMC_RCLONE_PATH": "environment-rclone",
        "HMC_LINKS_JOURNAL": "~/environment-links.jsonl",
    }

    resolved = resolve_config(
        CliConfigOverrides(remote="cli:", config_path=config_path), environment=environment
    )

    assert resolved.remote == "cli:"
    assert resolved.rclone_path == "environment-rclone"
    assert resolved.links_journal is not None
    assert resolved.links_journal.name == "environment-links.jsonl"
    assert resolved.timeout_seconds == 120


def test_environment_selects_a_profile_and_cli_profile_wins_over_it(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[profiles.default]
remote = "default:"

[profiles.work]
remote = "work:"
""".strip(),
        encoding="utf-8",
    )

    from_environment = resolve_config(
        CliConfigOverrides(config_path=config_path), environment={"HMC_PROFILE": "work"}
    )
    from_cli = resolve_config(
        CliConfigOverrides(profile="default", config_path=config_path),
        environment={"HMC_PROFILE": "work"},
    )

    assert (from_environment.profile, from_environment.remote) == ("work", "work:")
    assert (from_cli.profile, from_cli.remote) == ("default", "default:")


def test_secret_bearing_config_field_is_rejected_without_echoing_its_value(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[profiles.default]\nremote = "mailru:"\npassword = "password-sentinel"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as caught:
        resolve_config(CliConfigOverrides(config_path=config_path), environment={})

    assert caught.value.error.kind is ErrorKind.CONFIG_ERROR
    assert caught.value.error.exit_code == 3
    assert caught.value.error.details == {"field": "password"}
    assert "password-sentinel" not in str(caught.value)
    assert "password" not in {field.name for field in fields(ResolvedConfig)}


def test_config_cannot_weaken_frozen_public_root_or_confirmation_policy(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[profiles.default]
remote = "mailru:"
public_root = "/Personal/public"
require_yes_for_destructive = false
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as caught:
        resolve_config(CliConfigOverrides(config_path=config_path), environment={})

    assert caught.value.error.details == {"field": "public_root"}


@pytest.mark.parametrize("timeout_value", ["0", "-1", "true"])
def test_timeout_seconds_requires_a_positive_non_boolean_integer(
    tmp_path: Path, timeout_value: str
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[profiles.default]\ntimeout_seconds = {timeout_value}\nretries = 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as caught:
        resolve_config(CliConfigOverrides(config_path=config_path), environment={})

    assert caught.value.error.kind is ErrorKind.CONFIG_ERROR
    assert caught.value.error.details == {"field": "timeout_seconds"}


def test_retries_remains_a_nonnegative_integer_when_timeout_is_positive(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[profiles.default]\ntimeout_seconds = 1\nretries = 0\n", encoding="utf-8"
    )

    resolved = resolve_config(CliConfigOverrides(config_path=config_path), environment={})

    assert (resolved.timeout_seconds, resolved.retries) == (1, 0)


def test_sanitizer_covers_auth_token_cookie_mapping_and_public_url_patterns() -> None:
    public_url = "https://cloud.mail.ru/public/capability-token/path"
    raw = (
        "access_token=access-token-sentinel Password=password-sentinel "
        "Authorization: Bearer authorization-sentinel\n"
        "Cookie: session=cookie-sentinel\n"
        f"public={public_url}"
    )
    redacted = redact_text(raw)
    payload = sanitize_value(
        {"token": "mapping-token-sentinel", "nested": {"cookie": "mapping-cookie-sentinel"}}
    )
    rendered = render_json({"raw": raw, "payload": payload})

    for sentinel in (
        "access-token-sentinel",
        "password-sentinel",
        "authorization-sentinel",
        "cookie-sentinel",
        "mapping-token-sentinel",
        "mapping-cookie-sentinel",
        public_url,
    ):
        assert sentinel not in redacted + rendered
    assert "[REDACTED]" in rendered
    assert "public-url sha256:" in rendered


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("attempts=0 token=plain-secret bytes=7", "attempts=0 token=[REDACTED] bytes=7"),
        ("token='quoted secret' count=0", "token=[REDACTED] count=0"),
        ('prefix password="double secret" suffix', "prefix password=[REDACTED] suffix"),
        (
            "header\nAuthorization: Bearer header-secret\ncount=0",
            "header\nAuthorization: [REDACTED]\ncount=0",
        ),
        ("Cookie: session=cookie-secret\nattempts=0", "Cookie: [REDACTED]\nattempts=0"),
        (
            r"prefix {\"token\": \"escaped-secret\"} count=0",
            r"prefix {\"token\": \"[REDACTED]\"} count=0",
        ),
        (
            'prefix {"items":[{"token":"nested-secret"}],"count":0} suffix',
            'prefix {"items":[{"token":[REDACTED]}],"count":0} suffix',
        ),
        ("token=[REDACTED]", "token=[REDACTED]"),
        ("token=[REDACTED]suffix-secret attempts=0", "token=[REDACTED] attempts=0"),
        ("token=prefix-secret[REDACTED]suffix-secret bytes=7", "token=[REDACTED] bytes=7"),
        (
            "surrounding [REDACTED] token=additional-secret items=0",
            "surrounding [REDACTED] token=[REDACTED] items=0",
        ),
        ("token=[REDACTED][REDACTED]suffix-secret, count=0", "token=[REDACTED], count=0"),
        ("array=[token=[REDACTED]suffix-secret]; count=0", "array=[token=[REDACTED]]; count=0"),
        (
            "array=[token=[REDACTED]suffix-secret,42]; count=0",
            "array=[token=[REDACTED],42]; count=0",
        ),
        (
            '"password": "[REDACTED]suffix-secret", "attempts": 0',
            '"password": [REDACTED], "attempts": 0',
        ),
    ],
)
def test_redact_text_is_stable_without_trusting_redaction_markers(raw: str, expected: str) -> None:
    redacted = redact_text(raw)
    assert redacted == expected
    for _ in range(3):
        redacted = redact_text(redacted)
        assert redacted == expected


def test_nested_projection_and_envelope_json_remain_safe_and_idempotent() -> None:
    public_url = "https://cloud.mail.ru/public/repeated-redaction-synthetic/path"
    raw = {
        "items": [
            {"description": "marker [REDACTED] token=nested-sentinel attempts=0", "size": 0},
            ("password=[REDACTED]appended-sentinel", {"token": "[REDACTED]mapping-sentinel"}),
        ],
        "attempts": 0,
        "flag": False,
        "unknown": None,
        "safe_marker": "keep [REDACTED] unchanged",
        "public": public_url,
    }
    safe = sanitize_value(raw)
    assert len(safe["items"]) == 2
    assert safe["items"][0] == {
        "description": "marker [REDACTED] token=[REDACTED] attempts=0",
        "size": 0,
    }
    assert safe["items"][1] == ["password=[REDACTED]", {"token": "[REDACTED]"}]
    assert safe["attempts"] == 0 and safe["flag"] is False and safe["unknown"] is None
    assert safe["safe_marker"] == "keep [REDACTED] unchanged"
    for _ in range(3):
        assert sanitize_value(safe) == safe
    assert json.loads(render_json(raw)) == safe
    assert render_json(safe) == render_json(raw)
    envelopes = (
        ResultEnvelope.success("ls", raw, trace_id="token=[REDACTED]trace-sentinel"),
        ResultEnvelope.failure(
            "stat",
            ErrorPayload(ErrorKind.NOT_FOUND, "token=[REDACTED]message-sentinel", raw),
            warnings=("token=[REDACTED]warning-sentinel",),
        ),
    )
    for envelope in envelopes:
        assert json.loads(envelope.to_json()) == envelope.to_payload()
        assert envelope.to_payload()["ok"] is envelope.ok
    assert envelopes[1].exit_code == 7
    emitted = repr(safe) + render_json(raw) + "".join(item.to_json() for item in envelopes)
    for sentinel in (
        public_url,
        "nested-sentinel",
        "appended-sentinel",
        "mapping-sentinel",
        "trace-sentinel",
        "message-sentinel",
        "warning-sentinel",
    ):
        assert sentinel not in emitted
    assert "appended-sentinel" in raw["items"][1][0]
