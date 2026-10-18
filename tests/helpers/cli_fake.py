"""Test-only subprocess driver for the real CLI with a Python-argv fake rclone."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PUBLIC_URL = "https://cloud.mail.ru/public/cli-harness-capability/path"

_FAKE_RCLONE_SOURCE = """
import json
import os
import subprocess
import sys
from pathlib import Path

control_path = Path(__file__).with_name("rclone-control.json")
control = json.loads(control_path.read_text(encoding="utf-8"))
arguments = sys.argv[1:]
log_path = Path(control["log"])
with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps(arguments, ensure_ascii=False) + "\\n")

sabotage = control.get("sabotage")
if sabotage and arguments and arguments[0] == sabotage.get("command"):
    target = Path(sabotage["journal"])
    if sabotage["mode"] == "broaden-lock":
        target = target.with_name(f".{target.name}.lock")
    if os.name == "nt":
        subprocess.run(
            [sys.executable, control["worker"], "broaden", str(target)],
            check=True,
            timeout=10,
            capture_output=True,
        )
    else:
        target.chmod(0o644)

responses = control.get("responses") or {}
response = responses.get(json.dumps(arguments, ensure_ascii=False))
if response is None and arguments:
    response = responses.get(arguments[0])
if response is None:
    response = {}
if "sequence" in response:
    sequence = response["sequence"]
    calls = log_path.read_text(encoding="utf-8").splitlines()
    attempt = sum(json.loads(line) == arguments for line in calls) - 1
    response = sequence[min(attempt, len(sequence) - 1)]
if ("download_text" in response and len(arguments) > 2 and arguments[0] == "copyto"
        and Path(arguments[2]).is_absolute()):
    Path(arguments[2]).write_text(response["download_text"], encoding="utf-8")
stdout = response.get("stdout")
if stdout is None and arguments and arguments[0] == "link":
    stdout = control.get("default_link_url", "") + "\\n"
sys.stdout.write(stdout or "")
sys.stderr.write(response.get("stderr", ""))
raise SystemExit(response.get("returncode", 0))
"""


@dataclass(frozen=True, slots=True)
class CliFakeHarness:
    """One isolated fake backend, config file and private journal for a child CLI run."""

    root: Path
    backend_dir: Path
    script: Path
    control: Path
    calls: Path
    config: Path
    journal: Path
    worker: Path

    @classmethod
    def create(cls, root: Path) -> CliFakeHarness:
        backend_dir = root / "fake-backend"
        backend_dir.mkdir()
        script = backend_dir / "fake_rclone.py"
        script.write_text(_FAKE_RCLONE_SOURCE, encoding="utf-8")
        config = root / "config" / "config.toml"
        config.parent.mkdir()
        config.write_text("[profiles.default]\n", encoding="utf-8")
        return cls(
            root=root,
            backend_dir=backend_dir,
            script=script,
            control=backend_dir / "rclone-control.json",
            calls=backend_dir / "rclone-calls.jsonl",
            config=config,
            journal=root / "journal-state" / "links.jsonl",
            worker=Path(__file__).with_name("journal_worker.py"),
        )

    def run(
        self,
        *arguments: str,
        responses: Mapping[str, Mapping[str, object]] | None = None,
        sabotage: Mapping[str, str] | None = None,
        timeout: float = 30,
        extra_environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        control: dict[str, object] = {
            "log": str(self.calls),
            "default_link_url": PUBLIC_URL,
            "responses": dict(responses or {}),
            "worker": str(self.worker),
        }
        if sabotage is not None:
            control["sabotage"] = dict(sabotage)
        self.control.write_text(json.dumps(control, ensure_ascii=False), encoding="utf-8")
        environment = isolated_environment(self.root)
        environment.update(
            {
                "HMC_CONFIG": str(self.config),
                "HMC_REMOTE": "fake:",
                "HMC_RCLONE_PATH": str(self.script),
                "HMC_LINKS_JOURNAL": str(self.journal),
            }
        )
        if extra_environment:
            environment.update(extra_environment)
        return subprocess.run(
            [sys.executable, "-c", _driver_code(self.script), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=environment,
        )

    def recorded_calls(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [
            json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines() if line
        ]


def isolated_environment(root: Path) -> dict[str, str]:
    """Build a synthetic, secret-free environment for the child CLI process."""
    home = root / "empty-home"
    config_home = root / "empty-config-home"
    app_data = root / "empty-appdata"
    local_app_data = root / "empty-localappdata"
    temp = root / "empty-temp"
    empty_path = root / "empty-path"
    for directory in (home, config_home, app_data, local_app_data, temp, empty_path):
        directory.mkdir(parents=True, exist_ok=True)
    environment = {
        "PATH": str(empty_path),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(config_home),
        "APPDATA": str(app_data),
        "LOCALAPPDATA": str(local_app_data),
        "TEMP": str(temp),
        "TMP": str(temp),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(SRC_ROOT),
    }
    if os.name == "nt":
        environment["SystemRoot"] = os.environ.get("SystemRoot", "C:\\Windows")
    return environment


def _driver_code(script: Path) -> str:
    return "\n".join(
        (
            "import sys",
            "import hermes_mailcloud.cli as cli",
            "from hermes_mailcloud.rclone.runner import RcloneRunner as _RealRunner",
            "class _FakeRunner(_RealRunner):",
            "    def __init__(self, binary='rclone', **kwargs):",
            f"        super().__init__((sys.executable, {str(script)!r}), **kwargs)",
            "cli.RcloneRunner = _FakeRunner",
            "sys.argv = ['hermes-mailcloud', *sys.argv[1:]]",
            "cli.app()",
            "",
        )
    )


__all__ = ["CliFakeHarness", "PUBLIC_URL", "isolated_environment"]
