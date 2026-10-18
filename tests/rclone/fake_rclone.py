"""Deterministic fake executable for rclone-runner subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    scenario, *arguments = sys.argv[1:]
    if scenario == "success":
        print(
            json.dumps(
                {
                    "arguments": arguments,
                    "environment": dict(os.environ),
                },
                sort_keys=True,
            )
        )
        return 0
    if scenario == "error":
        sys.stderr.write("network unreachable token=runner-secret-sentinel\n")
        return 17
    if scenario == "timeout":
        time.sleep(5)
        return 0
    if scenario == "timeout-descendant":
        pid_path = Path(arguments[0])
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        pid_path.write_text(str(child.pid), encoding="ascii")
        time.sleep(3)
        return 0
    if scenario == "exit-with-descendant":
        pid_path = Path(arguments[0])
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        pid_path.write_text(str(child.pid), encoding="ascii")
        return 0
    if scenario == "malformed":
        sys.stdout.write("{not-valid-json")
        return 0
    if scenario == "overflow":
        sys.stdout.write("o" * 4096)
        sys.stderr.write("e" * 4096)
        return 0
    raise ValueError(f"unknown fake rclone scenario: {scenario}")


if __name__ == "__main__":
    raise SystemExit(main())
