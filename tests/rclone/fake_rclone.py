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
    if scenario in {"timeout-descendant", "exit-with-descendant"}:
        ready_path = Path(arguments[0])
        child_code = (
            "import json,os,sys,time; from pathlib import Path; "
            "stat=Path('/proc/self/stat'); "
            "ticks=stat.read_text().rsplit(')',1)[1].split()[19] if stat.exists() else None; "
            "payload={'pid':os.getpid(),'start_ticks':ticks,'ready':True}; "
            "target=Path(sys.argv[1]); temporary=target.with_suffix('.tmp'); "
            "temporary.write_text(json.dumps(payload),encoding='ascii'); "
            "os.replace(temporary,target); time.sleep(10)"
        )
        child = subprocess.Popen([sys.executable, "-c", child_code, str(ready_path)])
        deadline = time.monotonic() + 5
        while not ready_path.exists():
            if child.poll() is not None or time.monotonic() >= deadline:
                return 98
            time.sleep(0.005)
        if scenario == "timeout-descendant":
            time.sleep(10)
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
