"""Entry point for the isolated file-operations probe."""

from hermes_mailcloud.probes.core import main

if __name__ == "__main__":
    raise SystemExit(main("01_file_ops_probe"))
