"""Default lazy dependencies, with the same explicit environment at both edges."""

from __future__ import annotations

from collections.abc import Mapping

from ..config import ConfigOverrides, ResolvedConfig, resolve_config
from ..rclone.install import prepare_rclone as prepare_rclone
from ..rclone.runner import RcloneRunner
from .contracts import Backend


def load_config(overrides: ConfigOverrides, *, environment: Mapping[str, str]) -> ResolvedConfig:
    return resolve_config(overrides, environment=environment)


def create_backend(config: ResolvedConfig, *, environment: Mapping[str, str]) -> Backend:
    return RcloneRunner(config.rclone_path, environment=environment)
