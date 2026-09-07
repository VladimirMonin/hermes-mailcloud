---
name: mailru-cloud
description: >
  Use when a user asks to manage Mail.ru Cloud / Облако Mail.ru / Mail Disk
  files: list, inspect, upload, download, move, copy, delete, publish/link,
  batch, or access check; Russian triggers include загрузить, скачать,
  переместить, скопировать, удалить, опубликовать, ссылка, список файлов.
  Do not use for other cloud providers, generic/local storage, or Mail.ru email.
version: 1.0.0
---

# Mail.ru Cloud through hermes-mailcloud

> АГЕНТ: ЧИТАЙ ЭТОТ ФАЙЛ ЦЕЛИКОМ. AGENT: READ THIS FILE COMPLETELY. This is a short router; use the project documentation for full command and safety contracts.

## Trigger and boundary

Use this skill for requests in Russian or English to work with **files** in
Mail.ru Cloud: «загрузить файл в Облако Mail.ru», «скачать из Mail Disk»,
«список файлов», «переместить/скопировать/удалить файл», «создать публичную
ссылку», `upload`, `download`, `list`, `move`, `copy`, `delete`, `publish`,
`link`, `batch`, or an access/readiness check.

Do **not** use it for Google Drive, Dropbox, OneDrive, S3, Yandex Disk, or any
other cloud provider; generic file-management or local-disk storage; or Mail.ru
email, inbox, messages, contacts, and SMTP/IMAP tasks. Route those requests to
their provider- or email-specific capability instead.

## Available interface

- Prefer the stable non-editable command: `hermes-mailcloud ... --json`.
- During development from a repository checkout, use `uv run hermes-mailcloud ...`.
- For the installed command's implemented surface, use `hermes-mailcloud --help`
  and `hermes-mailcloud <command> --help`; command help takes precedence for
  the installed version.
- After the public immutable `v0.1.0a0` tag exists, standalone references are:
  [README](https://raw.githubusercontent.com/VladimirMonin/hermes-mailcloud/v0.1.0a0/README.md),
  [release policy](https://raw.githubusercontent.com/VladimirMonin/hermes-mailcloud/v0.1.0a0/docs/10-v0.1-release-notes.md),
  and [local setup](https://raw.githubusercontent.com/VladimirMonin/hermes-mailcloud/v0.1.0a0/docs/11-local-installation.md).
- Commands: `doctor`, `ls`, `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, and `batch`.
- `unlink` is not supported in v0.1 because live evidence did not prove URL invalidation.

## Workflow

1. If readiness is uncertain, run `hermes-mailcloud --json doctor`.
2. Read `ok`, `result`/`error`, and the process exit code; do not parse pretty output.
3. For writes, use `--dry-run` first when supported. Never automatically retry an ambiguous write.
4. Add `--yes` only for confirmation-gated operations such as `rm`, `publish`, write-batch, and live doctor.
5. Keep any opt-in live doctor/probe mutation in a unique `/TEST/hermes-mailcloud-*/` root. Ordinary `publish` is not a test mechanism; never use a public-root path for test work.
6. Verify mutations by read-back: `stat`/`ls`, size and SHA-256 for transfers, HTTP/browser check for public links.
7. Return a raw public URL only to the requesting owner. Never store it in Git, shared logs, Kanban, or public artifacts.
8. Delete local or cloud files only when the user explicitly requested that exact cleanup.

## Large files

Use a suitable timeout such as `--timeout 600`. Compare size and SHA-256 before upload and after round-trip download. Remove local test copies only after verification.
