"""Synthetic settings and a recording external runner edge, not application behavior."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from tests.helpers.cli_fake import isolated_environment

from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunner


class RecordingBackend(RcloneRunner):
    """Replace execution only; retain the real require_success/error mapping."""

    def __init__(
        self, *responses: RcloneResult | BaseException | Callable[[Sequence[str]], RcloneResult]
    ) -> None:
        super().__init__("never-executed-rclone", environment={})
        self.responses = list(responses)
        self.calls: list[tuple[list[str], float | None]] = []

    def run(self, args: Sequence[str], *, timeout_seconds: float | None = None) -> RcloneResult:
        self.calls.append((list(args), timeout_seconds))
        if not self.responses:
            raise AssertionError("unexpected external backend call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response(args) if callable(response) else response


def synthetic_environment(
    root: Path, contents: str = '[profiles.default]\nremote = "fake:"\n'
) -> dict[str, str]:
    environment = isolated_environment(root)
    config = root / "application.toml"
    config.write_text(contents, encoding="utf-8")
    backend_config = root / "empty-rclone.conf"
    backend_config.write_text("", encoding="utf-8")
    environment.update(
        HMC_CONFIG=str(config),
        HMC_RCLONE_PATH=str(root / "absent-rclone.exe"),
        HMC_LINKS_JOURNAL=str(root / "private-leaf" / "links.jsonl"),
        RCLONE_CONFIG=str(backend_config),
        TMPDIR=environment["TEMP"],
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    return environment
