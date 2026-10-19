---
name: mailru-cloud
description: >
  Use when the user asks to work with Mail.ru Cloud, Mail Disk, or Облако Mail:
  list, inspect, upload, download, move, copy, delete, publish, create a public
  link, run a batch, prepare rclone, or check access through hermes-mailcloud.
version: 1.0.0
---

# Mail.ru Cloud through hermes-mailcloud

> АГЕНТ: ЧИТАЙ ЭТОТ ФАЙЛ ЦЕЛИКОМ. AGENT: READ THIS FILE COMPLETELY. This is a short router; use the project documentation for full command and safety contracts.

## Available interface

- Prefer the stable non-editable `uv tool` command: `hermes-mailcloud ... --json`.
- During development, use `uv run hermes-mailcloud ...` from the repository checkout.
- Source of truth: repository `README.md` and `docs/README.md`.
- Commands: explicit dependency `setup`, read-only `doctor`, `ls`, `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, and `batch`.
- `unlink` is not supported in v0.1 because live evidence did not prove URL invalidation.

## Workflow

1. After package installation, explicitly run `hermes-mailcloud --json setup`, then read-only `doctor`. Setup prepares pinned official Windows/Linux amd64 rclone, not a cloud account; no manual executable/PATH step. Later, if readiness is uncertain, use `doctor`. An invalid explicit `HMC_RCLONE_PATH`/profile `rclone_path` must be corrected separately, never silently bypassed.
2. Read `ok`, `result`/`error`, and the process exit code; do not parse pretty output.
3. For writes, use `--dry-run` first when supported. Never automatically retry an ambiguous write.
4. Add `--yes` only for confirmation-gated operations such as `rm`, `publish`, write-batch, and live doctor.
5. Keep test mutations in a unique `/TEST/<run-id>/`; test publications belong under `/Hermes/public/TEST/` because public paths are policy-restricted.
6. Verify mutations by read-back: `stat`/`ls`, size and SHA-256 for transfers, HTTP/browser check for public links.
7. Return a raw public URL only to the requesting owner. Never store it in Git, shared logs, Kanban, or public artifacts.
8. Delete local or cloud files only when the user explicitly requested that exact cleanup.

## Large files

Use a suitable timeout such as `--timeout 600`. Compare size and SHA-256 before upload and after round-trip download. Remove local test copies only after verification.

## Stable install and refresh

From a clean accepted repository revision:

```bash
uv tool install --force --python 3.12 .
hermes-mailcloud --json setup
hermes-mailcloud version
hermes-mailcloud --json doctor
```

The installed command must remain non-editable so branch changes and uncommitted development cannot alter the operational CLI. Help/version/doctor/file commands never download implicitly. Setup keeps a valid external or existing managed copy; package refresh is not an automatic rclone update. Offline `setup --archive` requires the exact packaged official pin. Storage, supported targets, separate interactive cloud configuration and limits are in `docs/11-local-installation.md`; binaries are not bundled in the Python package.
