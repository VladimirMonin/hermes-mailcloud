"""Unit test — package imports and version is a string."""

import tomllib
from pathlib import Path

from hermes_mailcloud import __version__


def test_version_is_string() -> None:
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_runtime_version_matches_project_and_lockfile() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = [package for package in lock["package"] if package["name"] == project["name"]]

    assert len(packages) == 1
    assert __version__ == project["version"] == packages[0]["version"]
