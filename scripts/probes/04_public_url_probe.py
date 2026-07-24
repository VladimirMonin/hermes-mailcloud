"""Entry point for the bounded public-URL HTTP probe."""

from hermes_mailcloud.probes.core import main

if __name__ == "__main__":
    raise SystemExit(main("04_public_url_probe"))
