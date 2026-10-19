"""Strict secret-free configuration loading with documented precedence."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core.errors import ErrorKind, ErrorPayload, MailCloudError
from .core.paths import RemotePathError, normalize_remote_path, validate_rclone_remote
from .core.policy import PUBLIC_ROOT
from .rclone.install import external_rclone_path, managed_rclone_path

DEFAULT_PROFILE = "default"
DEFAULT_RCLONE_PATH = "rclone"
DEFAULT_PRIVATE_ROOT = "/Hermes/private"
DEFAULT_TEMP_ROOT = "/Hermes/.tmp"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRIES = 0
PROFILE_FIELDS = frozenset(
    {
        "remote",
        "rclone_path",
        "private_root",
        "public_root",
        "temp_root",
        "links_journal",
        "default_overwrite",
        "deny_dangerous_publish",
        "require_yes_for_destructive",
        "probe_public_url_after_publish",
        "timeout_seconds",
        "retries",
    }
)


@dataclass(frozen=True, slots=True)
class CliConfigOverrides:
    """Only the global config inputs resolved before command-specific options."""

    profile: str | None = None
    remote: str | None = None
    config_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Effective non-secret settings for one named profile."""

    profile: str
    config_path: Path
    remote: str | None
    rclone_path: str
    private_root: str
    public_root: str
    temp_root: str
    links_journal: Path | None
    default_overwrite: str
    deny_dangerous_publish: bool
    require_yes_for_destructive: bool
    probe_public_url_after_publish: bool
    timeout_seconds: int
    retries: int
    rclone_path_explicit: bool = False


class ConfigError(MailCloudError):
    """A secret-free configuration failure mapped to stable exit code 3."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        details: dict[str, str] = {"field": field} if field else {}
        super().__init__(ErrorPayload(ErrorKind.CONFIG_ERROR, message, details))


def default_config_path(environment: Mapping[str, str] | None = None) -> Path:
    """Return the platform-neutral default without creating parent directories."""
    env = os.environ if environment is None else environment
    config_home = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "hermes-mailcloud" / "config.toml"


def resolve_config(
    cli: CliConfigOverrides | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> ResolvedConfig:
    """Resolve CLI > environment > profile file > defaults without credential fields."""
    cli = cli or CliConfigOverrides()
    env = os.environ if environment is None else environment
    config_path, config_was_explicit = _resolve_config_path(cli, env)
    profiles = _load_profiles(config_path, required=config_was_explicit)
    profile_name = cli.profile or env.get("HMC_PROFILE") or DEFAULT_PROFILE
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ConfigError("profile must be a non-empty string", field="profile")
    profile = _profile_for_name(profiles, profile_name)

    remote = _first_not_none(cli.remote, env.get("HMC_REMOTE"), profile.get("remote"))
    if remote is not None:
        try:
            remote = validate_rclone_remote(_expect_str(remote, "remote"))
        except RemotePathError as exc:
            raise ConfigError(
                "remote must be a simple rclone remote name ending in ':'", field="remote"
            ) from exc

    public_root = _normalized_profile_path(profile, "public_root", PUBLIC_ROOT)
    if public_root != PUBLIC_ROOT:
        raise ConfigError("public_root is fixed to /Hermes/public in v0.1", field="public_root")

    deny_dangerous_publish = _profile_bool(profile, "deny_dangerous_publish", True)
    require_yes_for_destructive = _profile_bool(profile, "require_yes_for_destructive", True)
    if not deny_dangerous_publish:
        raise ConfigError(
            "deny_dangerous_publish cannot be disabled in v0.1", field="deny_dangerous_publish"
        )
    if not require_yes_for_destructive:
        raise ConfigError(
            "require_yes_for_destructive cannot be disabled in v0.1",
            field="require_yes_for_destructive",
        )

    journal_value = _first_not_none(env.get("HMC_LINKS_JOURNAL"), profile.get("links_journal"))
    journal = (
        Path(_expect_str(journal_value, "links_journal")).expanduser() if journal_value else None
    )
    timeout_seconds = _profile_positive_int(profile, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    retries = _profile_nonnegative_int(profile, "retries", DEFAULT_RETRIES)
    overwrite = _profile_choice(
        profile, "default_overwrite", "never", {"never", "always", "if-newer"}
    )
    rclone_override = _first_not_none(env.get("HMC_RCLONE_PATH"), profile.get("rclone_path"))
    rclone_path = _expect_str(
        rclone_override if rclone_override is not None else DEFAULT_RCLONE_PATH, "rclone_path"
    )
    if rclone_override is None and external_rclone_path(DEFAULT_RCLONE_PATH, env) is None:
        managed = managed_rclone_path(env)
        if managed is not None:
            rclone_path = str(managed)

    return ResolvedConfig(
        profile=profile_name,
        config_path=config_path,
        remote=remote,
        rclone_path=rclone_path,
        rclone_path_explicit=rclone_override is not None,
        private_root=_normalized_profile_path(profile, "private_root", DEFAULT_PRIVATE_ROOT),
        public_root=public_root,
        temp_root=_normalized_profile_path(profile, "temp_root", DEFAULT_TEMP_ROOT),
        links_journal=journal,
        default_overwrite=overwrite,
        deny_dangerous_publish=deny_dangerous_publish,
        require_yes_for_destructive=require_yes_for_destructive,
        probe_public_url_after_publish=_profile_bool(
            profile, "probe_public_url_after_publish", True
        ),
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def _resolve_config_path(cli: CliConfigOverrides, env: Mapping[str, str]) -> tuple[Path, bool]:
    value = _first_not_none(cli.config_path, env.get("HMC_CONFIG"))
    if value is None:
        return default_config_path(env), False
    if isinstance(value, Path):
        return value.expanduser(), True
    return Path(_expect_str(value, "config_path")).expanduser(), True


def _load_profiles(path: Path, *, required: bool) -> dict[str, dict[str, Any]]:
    if not path.exists():
        if required:
            raise ConfigError("configured config file does not exist", field="config_path")
        return {}
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            "could not read a valid TOML configuration file", field="config_path"
        ) from exc
    if not isinstance(loaded, dict) or set(loaded) - {"profiles"}:
        raise ConfigError("configuration permits only a top-level profiles table")
    raw_profiles = loaded.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ConfigError("profiles must be a TOML table", field="profiles")

    profiles: dict[str, dict[str, Any]] = {}
    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str) or not isinstance(raw_profile, dict):
            raise ConfigError("each profile must be a named TOML table", field="profiles")
        unknown = set(raw_profile) - PROFILE_FIELDS
        if unknown:
            raise ConfigError(
                "configuration contains an unsupported or secret-bearing field",
                field=sorted(unknown)[0],
            )
        profiles[name] = dict(raw_profile)
    return profiles


def _profile_for_name(profiles: Mapping[str, dict[str, Any]], profile_name: str) -> dict[str, Any]:
    if profiles and profile_name not in profiles:
        raise ConfigError("requested profile is not configured", field="profile")
    return dict(profiles.get(profile_name, {}))


def _normalized_profile_path(profile: Mapping[str, Any], field: str, default: str) -> str:
    try:
        return normalize_remote_path(_expect_str(profile.get(field, default), field))
    except RemotePathError as exc:
        raise ConfigError(f"{field} must be an absolute POSIX path", field=field) from exc


def _profile_bool(profile: Mapping[str, Any], field: str, default: bool) -> bool:
    value = profile.get(field, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a boolean", field=field)
    return value


def _profile_positive_int(profile: Mapping[str, Any], field: str, default: int) -> int:
    value = profile.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer", field=field)
    return value


def _profile_nonnegative_int(profile: Mapping[str, Any], field: str, default: int) -> int:
    value = profile.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{field} must be a non-negative integer", field=field)
    return value


def _profile_choice(profile: Mapping[str, Any], field: str, default: str, choices: set[str]) -> str:
    value = _expect_str(profile.get(field, default), field)
    if value not in choices:
        raise ConfigError(f"{field} has an unsupported value", field=field)
    return value


def _expect_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string", field=field)
    return value


def _first_not_none(*values: object) -> object | None:
    return next((value for value in values if value is not None), None)
