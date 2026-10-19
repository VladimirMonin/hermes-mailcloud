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

- Current stable package: **0.1.0**, GitHub Release only, not PyPI. Prefer the isolated persistent `uv tool` command for regular agent use: `hermes-mailcloud ... --json`. uv tool is built into uv and convenient, not mandatory; no checkout is needed.
- During development, use `uv run hermes-mailcloud ...` from the repository checkout.
- Source of truth: repository `README.md` and `docs/README.md`.
- Commands: explicit dependency `setup`, read-only `doctor`, `ls`, `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, and `batch`.
- `unlink` is not supported in v0.1 because live evidence did not prove URL invalidation.

## Workflow

1. After package installation, explicitly run `hermes-mailcloud --json setup`, then read-only `doctor`. Setup prepares pinned official Windows/Linux amd64 rclone, not a cloud account; no manual executable/PATH step. Later, if readiness is uncertain, use `doctor`. An invalid explicit `HMC_RCLONE_PATH`/profile `rclone_path` must be corrected separately, never silently bypassed.
2. For a saved connection, select its application `--config` and matching explicit `--profile`, and pass the separate backend `RCLONE_CONFIG` in the invoking process environment. A default refusal does not prove credentials absent; never open/copy secret configuration bodies or request credentials in chat. Read `ok`, `result`/`error`, and the process exit code; do not parse pretty output.
3. For writes, use `--dry-run` first when supported. Never automatically retry an ambiguous write.
4. Add `--yes` only for confirmation-gated operations such as `rm`, `publish`, write-batch, and live doctor.
5. Keep test mutations in the authorized unique `/TEST/<run-id>/`. A path there does not satisfy the `/Hermes/public` publication policy; that policy does not itself authorize a different test root. If both constraints cannot be met, stop and request an explicit owner decision; do not broaden either scope.
6. Verify mutations by read-back: `stat`/`ls`, size and SHA-256 for transfers. A bounded public-link HTTP/browser check may prove only an HTML landing page, not document-byte download or revocation.
7. Normal JSON returns a public-link fingerprint; the raw capability remains in the owner-private journal. Share only fingerprints in handoffs. Never put raw URLs in Git, chat, shared logs, Kanban, or public artifacts.
8. Delete local or cloud files only when the user explicitly requested that exact cleanup.

## Large files

Use a suitable timeout such as `--timeout 600`. Compare size and SHA-256 before upload and after round-trip download. Remove local test copies only after verification.

## Non-editable install and refresh

Install uv using its official installation guide; no separate uv-tool package.
Use the pinned GitHub wheel (Python >=3.12, qualification targets 3.12/3.13):

```console
uv tool install --python 3.12 https://github.com/VladimirMonin/hermes-mailcloud/releases/download/v0.1.0/hermes_mailcloud-0.1.0-py3-none-any.whl
hermes-mailcloud --json setup
hermes-mailcloud version
hermes-mailcloud --json doctor
```

To intentionally replace an older GitHub-wheel installation, repeat that exact URL with `uv tool install --force --python 3.12`; do not assume a registry-name auto-upgrade. Verify `version` reports 0.1.0. If command discovery fails, use `uv tool dir --bin` and the exact launcher path; shell setup and alternatives are in the install guide. The installed command must remain non-editable so branch changes and uncommitted development cannot alter the operational CLI. Help/version/doctor/file commands never download implicitly. Setup keeps a valid external or existing managed copy; package refresh is not an automatic rclone update. Offline `setup --archive` requires the exact packaged official pin. Storage, supported targets, separate interactive cloud configuration and limits are in `docs/11-local-installation.md`; binaries are not bundled in the Python package.
