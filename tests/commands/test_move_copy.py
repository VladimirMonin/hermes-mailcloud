"""Fake-backend tests for remote move and copy commands."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_mailcloud.commands.move_copy import MoveCopyCommands
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult


@dataclass
class RecordingBackend:
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        return RcloneResult(0, "", "", 1)


def _config(*, remote: str | None = "mailru:") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=None,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


@pytest.mark.parametrize(("method", "rclone_command"), [("move", "moveto"), ("copy", "copyto")])
@pytest.mark.parametrize(
    ("overwrite", "expected_flag"),
    [("never", "--immutable"), ("always", "--ignore-times"), ("if-newer", "--update")],
)
def test_move_and_copy_pass_exact_validated_argv(
    method: str, rclone_command: str, overwrite: str, expected_flag: str
) -> None:
    backend = RecordingBackend()
    commands = MoveCopyCommands(backend, _config(), timeout_seconds=13)

    result = getattr(commands, method)(
        "/Hermes/private/./source.txt", "/Hermes/private/target.txt", overwrite=overwrite
    )

    operation = "mv" if method == "move" else "cp"
    assert result == {
        "source_path": "/Hermes/private/source.txt",
        "target_path": "/Hermes/private/target.txt",
        "overwrite": overwrite,
    }
    assert backend.calls == [
        (
            (
                rclone_command,
                "mailru:/Hermes/private/source.txt",
                "mailru:/Hermes/private/target.txt",
                expected_flag,
            ),
            13,
        )
    ]
    assert operation in {"mv", "cp"}


@pytest.mark.parametrize("method", ["move", "copy"])
def test_move_and_copy_dry_run_do_not_start_rclone(method: str) -> None:
    backend = RecordingBackend()
    commands = MoveCopyCommands(backend, _config(), timeout_seconds=60)

    result = getattr(commands, method)(
        "/Hermes/private/source.txt", "/Hermes/private/target.txt", dry_run=True
    )

    assert result["dry_run"] is True
    assert result["overwrite"] == "never"
    assert backend.calls == []


@pytest.mark.parametrize("method", ["move", "copy"])
def test_move_and_copy_reject_identical_paths_before_rclone(method: str) -> None:
    backend = RecordingBackend()
    commands = MoveCopyCommands(backend, _config(), timeout_seconds=60)

    with pytest.raises(MailCloudError) as caught:
        getattr(commands, method)("/Hermes/private/file.txt", "/Hermes/private/./file.txt")

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


@pytest.mark.parametrize("method", ["move", "copy"])
def test_move_and_copy_reject_write_retry_budgets_before_rclone(method: str) -> None:
    backend = RecordingBackend()
    commands = MoveCopyCommands(backend, _config(), timeout_seconds=60)

    with pytest.raises(MailCloudError) as caught:
        getattr(commands, method)(
            "/Hermes/private/source.txt", "/Hermes/private/target.txt", retries=1
        )

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []
