"""Entry point for the isolated unlink capability probe."""

from hermes_mailcloud.probes.core import main

if __name__ == "__main__":
    raise SystemExit(main("03_unlink_probe"))
