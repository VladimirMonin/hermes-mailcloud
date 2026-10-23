"""Real resolver precedence, per-call configuration and explicit environment wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.application import RecordingBackend, synthetic_environment

from hermes_mailcloud.application import (
    CallOptions,
    ConfigOverrides,
    MailCloudApplication,
    composition,
)
from hermes_mailcloud.config import DEFAULT_RETRIES, DEFAULT_TIMEOUT_SECONDS
from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.rclone.runner import RcloneResult


@pytest.mark.parametrize(
    ("overrides", "env_profile", "env_remote", "profile", "remote"),
    [
        (ConfigOverrides(), None, None, "default", "profile:"),
        (ConfigOverrides(), "work", None, "work", "work:"),
        (ConfigOverrides(profile="default"), "work", None, "default", "profile:"),
        (ConfigOverrides(), "work", "environment:", "work", "environment:"),
        (ConfigOverrides(remote="explicit:"), "work", "environment:", "work", "explicit:"),
    ],
)
def test_direct_config_precedence_uses_real_resolver(
    tmp_path: Path, overrides, env_profile, env_remote, profile, remote
) -> None:
    environment = synthetic_environment(
        tmp_path, '[profiles.default]\nremote="profile:"\n[profiles.work]\nremote="work:"\n'
    )
    if env_profile is not None:
        environment["HMC_PROFILE"] = env_profile
    if env_remote is not None:
        environment["HMC_REMOTE"] = env_remote
    backend = RecordingBackend(RcloneResult(0, "[]", "", 0))
    app = MailCloudApplication(
        environment=environment, backend_factory=lambda config, **kw: backend
    )
    result = app.ls("/Hermes", options=CallOptions(config=overrides))
    assert result.ok
    assert (result.profile, result.remote) == (profile, remote)
    assert backend.calls == [(["lsjson", remote + "/Hermes"], DEFAULT_TIMEOUT_SECONDS)]


def test_config_file_override_wins_over_environment(tmp_path: Path) -> None:
    environment = synthetic_environment(tmp_path)
    other = tmp_path / "explicit.toml"
    other.write_text('[profiles.default]\nremote="explicit:"\n', encoding="utf-8")
    backend = RecordingBackend(RcloneResult(0, "[]", "", 0))
    app = MailCloudApplication(
        environment=environment, backend_factory=lambda config, **kw: backend
    )
    result = app.ls("/Hermes", options=CallOptions(config=ConfigOverrides(config_path=other)))
    assert result.ok and result.remote == "explicit:"


def test_environment_snapshot_is_shared_and_config_and_backend_are_fresh_per_call(
    tmp_path: Path, monkeypatch
) -> None:
    environment = synthetic_environment(tmp_path)
    snapshot = dict(environment)
    loaded, built = [], []
    backends = []

    def loader(overrides, *, environment):
        loaded.append(environment)
        return composition.load_config(overrides, environment=environment)

    def factory(config, *, environment):
        built.append((config, environment))
        backend = RecordingBackend(RcloneResult(0, "[]", "", 0))
        backends.append(backend)
        return backend

    app = MailCloudApplication(
        environment=environment, config_loader=loader, backend_factory=factory
    )
    environment["HMC_REMOTE"] = "changed:"
    monkeypatch.setenv("HMC_REMOTE", "process-changed:")
    assert app.ls("/Hermes").ok
    Path(snapshot["HMC_CONFIG"]).write_text(
        '[profiles.default]\nremote="reread:"\ntimeout_seconds=7\nretries=2\n', encoding="utf-8"
    )
    assert app.ls("/Hermes").remote == "reread:"
    assert len(loaded) == len(built) == len(backends) == 2
    assert loaded[0] is loaded[1] is built[0][1] is built[1][1]
    assert dict(loaded[0]) == snapshot
    assert built[0][0] is not built[1][0]
    assert backends[0].calls == [(["lsjson", "fake:/Hermes"], DEFAULT_TIMEOUT_SECONDS)]
    assert backends[1].calls == [(["lsjson", "reread:/Hermes"], 7)]
    assert built[0][0].retries == DEFAULT_RETRIES and built[1][0].retries == 2


def test_default_constructor_copies_process_environment(tmp_path: Path, monkeypatch) -> None:
    environment = synthetic_environment(tmp_path)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HMC_PROFILE", "work")
    app = MailCloudApplication()
    monkeypatch.setenv("HMC_PROFILE", "changed")
    assert app.version().profile == "work"


@pytest.mark.parametrize(
    ("contents", "kind", "code"),
    [
        ("[profiles.default]\n", ErrorKind.REMOTE_NOT_CONFIGURED, 5),
        ('[profiles.default]\nremote=""\n', ErrorKind.CONFIG_ERROR, 3),
        ('[profiles.default]\npassword="config-secret"\n', ErrorKind.CONFIG_ERROR, 3),
        ("invalid TOML", ErrorKind.CONFIG_ERROR, 3),
    ],
)
def test_configuration_failures_are_safe_and_start_no_backend(
    tmp_path: Path, contents: str, kind: ErrorKind, code: int
) -> None:
    environment = synthetic_environment(tmp_path, contents)
    backend = RecordingBackend()
    result = MailCloudApplication(
        environment=environment, backend_factory=lambda config, **kw: backend
    ).stat("/Hermes")
    assert not result.ok and result.error.kind is kind and result.exit_code == code
    assert backend.calls == []
    assert "config-secret" not in repr(result)


def test_explicit_missing_executable_is_not_replaced_with_another_backend(tmp_path: Path) -> None:
    app = MailCloudApplication(environment=synthetic_environment(tmp_path))
    result = app.ls("/Hermes")
    assert result.error.kind is ErrorKind.RCLONE_NOT_FOUND and result.exit_code == 4


def test_actual_composition_passes_the_injected_environment_to_the_real_runner(
    tmp_path: Path,
) -> None:
    environment = synthetic_environment(tmp_path)
    config = composition.load_config(ConfigOverrides(), environment=environment)
    backend = composition.create_backend(config, environment=environment)
    assert backend._binary == (environment["HMC_RCLONE_PATH"],)
    assert backend._environment["RCLONE_CONFIG"] == environment["RCLONE_CONFIG"]
    assert backend._environment["HOME"] == environment["HOME"]
    # The existing runner deliberately filters the supplied snapshot; it does
    # not forward every process variable to the external executable.
    assert "USERPROFILE" not in backend._environment
    assert "HMC_CONFIG" not in backend._environment


def test_default_factory_is_selected_at_construction_not_default_argument_binding(
    tmp_path: Path, monkeypatch
) -> None:
    environment = synthetic_environment(tmp_path)
    backend = RecordingBackend(RcloneResult(0, "[]", "", 0))
    observed = []

    def factory(config, *, environment):
        observed.append((config.rclone_path, dict(environment)))
        return backend

    monkeypatch.setattr(composition, "create_backend", factory)
    app = MailCloudApplication(environment=environment)
    assert app.ls("/Hermes").ok
    assert observed == [(environment["HMC_RCLONE_PATH"], environment)]
