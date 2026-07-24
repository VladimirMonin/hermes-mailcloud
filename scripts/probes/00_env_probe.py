"""Entry point for the read-only rclone environment probe."""

from hermes_mailcloud.probes.core import main

if __name__ == "__main__":
    raise SystemExit(main("00_env_probe"))
