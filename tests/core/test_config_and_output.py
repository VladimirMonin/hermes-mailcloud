"""Tests for strict secret-free configuration and output redaction."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from hermes_mailcloud.config import CliConfigOverrides, ConfigError, ResolvedConfig, resolve_config
from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.output import redact_text, render_json, sanitize_value


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
