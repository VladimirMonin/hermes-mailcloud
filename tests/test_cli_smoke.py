"""Wave 0 smoke test — CLI version command works."""

from __future__ import annotations

import subprocess
import sys


def test_version_command() -> None:
    """`hermes-mailcloud version` prints the package version."""
    result = subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    from hermes_mailcloud import __version__

    assert __version__ in result.stdout


def test_help_command() -> None:
    """`hermes-mailcloud --help` exits 0 and mentions a known command."""
    result = subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "doctor" in result.stdout
