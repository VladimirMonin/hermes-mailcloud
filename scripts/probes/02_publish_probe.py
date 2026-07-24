"""Entry point for the isolated public-link capability probe."""

from hermes_mailcloud.probes.core import main

if __name__ == "__main__":
    raise SystemExit(main("02_publish_probe"))
