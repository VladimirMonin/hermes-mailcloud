# 02. Command Contract — Hermes MailCloud

<!-- hmc-json-example-default: result-envelope -->

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`  
> Назначение: зафиксировать команды, флаги, JSON-ответы и exit codes для агентской CLI-утилиты.

> [!important]
> **Frozen v0.1 contract (2026-07-24).** Required commands are `doctor`,
> `ls`, `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`,
> `link`, and `batch`. `unlink` is conditional: it is not shipped until a
> bounded live probe proves both `rclone link --unlink` and public-URL
> invalidation. `sync`, `resolve`, direct-download resolution, private API,
> link expiration/passwords, and full link audit are post-v0.1. `auth` is not
> a command: read-only `doctor` reports credential readiness without exposing
> credentials. This freeze takes precedence over older draft sections below.
> It is a target contract only: the current source tree remains a Wave 0
> skeleton until a later implementation stage proves each command.

---

## 1. Общий принцип 🧭

`hermes-mailcloud` должен быть удобен в первую очередь агентам.

Главное правило:

```text
В режиме --json команда никогда не задаёт интерактивных вопросов.
```

Если не хватает подтверждения, конфигурации или аргументов, команда должна вернуть JSON-ошибку и ненулевой exit code.

---

## 2. Общий формат вызова 🧰

```bash
hermes-mailcloud [GLOBAL_OPTIONS] COMMAND [ARGS] [COMMAND_OPTIONS]
```

Примеры:

```bash
hermes-mailcloud doctor --json
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

---

## 3. Глобальные опции ⚙️

| Флаг | Тип | По умолчанию | Назначение |
|---|---|---|---|
| `--profile` | text | `default` | профиль конфигурации |
| `--remote` | text | из конфига | rclone remote, например `mailru:` |
| `--config` | path | auto | путь к конфигу `hermes-mailcloud` |
| `--json` | bool | false | машинный JSON-вывод |
| `--pretty` | bool | false | человекочитаемый вывод |
| `--quiet` | bool | false | подавить лишний вывод |
| `--debug` | bool | false | подробная диагностика |
| `--trace-id` | text | auto | id операции для логов |
| `--dry-run` | bool | false | показать план без выполнения |
| `--yes` | bool | false | подтвердить опасную операцию |
| `--timeout` | int | 60 | timeout в секундах |
| `--retries` | int | 0 | only safe read-only work retries automatically; writes do not in v0.1 |
| `--no-color` | bool | false | отключить ANSI-цвета |

---

## 4. JSON envelope 📦

### 4.1 Успех

```json
{
  "ok": true,
  "operation": "publish",
  "trace_id": "2026-07-04T13-45-00Z-a1b2",
  "profile": "default",
  "remote": "mailru:",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "public_url_fingerprint": "sha256:example-public-link"
  },
  "warnings": []
}
```

### 4.2 Ошибка

```json
{
  "ok": false,
  "operation": "publish",
  "trace_id": "2026-07-04T13-45-00Z-a1b2",
  "profile": "default",
  "remote": "mailru:",
  "error": {
    "kind": "unsafe_public_path",
    "message": "Publishing is allowed only inside /Hermes/public.",
    "details": {
      "remote_path": "/Personal/report.pdf",
      "public_root": "/Hermes/public"
    },
    "exit_code": 9
  }
}
```

---

## 5. Exit codes 🚦

| Code | Значение |
|---:|---|
| `0` | success |
| `1` | unknown error |
| `2` | invalid arguments |
| `3` | config error |
| `4` | rclone not found |
| `5` | remote not configured |
| `6` | access denied / auth error |
| `7` | object not found |
| `8` | conflict |
| `9` | unsafe or forbidden action |
| `10` | network / retry exhausted |
| `11` | partial failure |
| `12` | backend unsupported |
| `13` | parse error |
| `14` | timeout |

---

## 5.1 Frozen cross-command invariants

`schemas/result-envelope.schema.json` is the normative envelope. Exactly one
of `result` and `error` is present. A normal failure has `ok: false` and a
typed `error` whose kind and exit code are an approved pair. Batch partial
failure is the sole exception to the usual failure shape: it has `ok: false`,
no top-level `error`, `result.status: "partial_failure"`, `result.items`, and
process exit code `11`.

Remote paths are absolute POSIX-style paths. Before policy or rclone receives a
path, the CLI must reject an empty path, NUL, relative paths, and normalized
traversal outside its intended root. User input never includes the rclone
remote prefix; it is assembled separately. `publish` and `link` validate the
normalized descendant relation to `/Hermes/public`, not a string prefix.

Every write command and `batch` supports `--dry-run`: it validates static
arguments and policy and returns a planned result without rclone calls,
mutations, journal writes, or URL probes. `--dry-run` never substitutes for
`--yes` during real execution. Automatic retries are limited to explicitly
safe read-only work. v0.1 makes no automatic retry of a write: ambiguous
side-effects must be surfaced as a typed result/error until a later,
operation-specific idempotency decision is documented and tested.

The local link journal is an owner-private capability store, not a cloud source
of truth. It records minimal operation metadata under local permissions; it
never stores raw provider stdout/stderr. A returned public URL may be retained
only locally for the owner, while Git, schemas, test artifacts, logs, Kanban
and chat use redacted placeholders or fingerprints. Redaction applies before
any diagnostic, journal or JSON `details` field is emitted.

---

## 6. Команда `doctor` 🩺

Проверяет готовность окружения.

### Вызов

```bash
hermes-mailcloud doctor --json
```

### Режимы проверок

`doctor --json` is read-only: it may report rclone availability/version,
configured remote and read-only cloud access, but it never creates an object or
calls link/unlink. `doctor --json --live` is the explicit mutating mode. Every
live run must use a newly generated descendant of `/TEST/<unique-run-id>/`,
record that normalized root, and clean up only objects created by that run.
Existing objects outside `/TEST` remain metadata/list-only.

### JSON успеха: read-only mode

<!-- hmc-json-example: doctor-report -->
```json
{
  "ok": true,
  "operation": "doctor",
  "result": {
    "mode": "read_only",
    "checks": {
      "rclone_installed": true,
      "rclone_version": "1.74.3",
      "remote_configured": true,
      "cloud_access": true
    },
    "capabilities": {
      "file_ops": "unknown",
      "public_link_create": "unknown",
      "public_link_unlink": "unknown"
    }
  }
}
```

Live mode adds only `/TEST`-scoped file-cycle, link, bounded URL and cleanup
checks. `unlink` becomes `supported` only after the same live run proves URL
invalidation; otherwise it is `unknown` or `unsupported` and remains absent
from the CLI.

---

## 7. Команда `ls` 📁

Показывает содержимое удалённой директории.

### Вызов

```bash
hermes-mailcloud ls /Hermes --json
```

### Опции

| Флаг | Назначение |
|---|---|
| `--recursive` | рекурсивный список |
| `--files-only` | только файлы |
| `--dirs-only` | только папки |

### JSON успеха

```json
{
  "ok": true,
  "operation": "ls",
  "result": {
    "remote_path": "/Hermes",
    "items": [
      {
        "path": "/Hermes/private",
        "name": "private",
        "type": "directory"
      },
      {
        "path": "/Hermes/public/report.pdf",
        "name": "report.pdf",
        "type": "file",
        "size": 18420,
        "modified": "2026-07-04T09:15:12Z"
      }
    ]
  }
}
```

---

## 8. Команда `stat` 🔎

Показывает метаданные файла или папки.

### Вызов

```bash
hermes-mailcloud stat /Hermes/public/report.pdf --json
```

### JSON успеха

```json
{
  "ok": true,
  "operation": "stat",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "type": "file",
    "size": 18420,
    "modified": "2026-07-04T09:15:12Z",
    "hash": {
      "mailru": "..."
    }
  }
}
```

---

## 9. Команда `mkdir` 📂

Создаёт папку в Облаке.

### Вызов

```bash
hermes-mailcloud mkdir /Hermes/private/reports --json
```

### Опции

| Флаг | Назначение |
|---|---|
| `--parents` | создать родительские директории, если backend позволяет |
| `--exist-ok` | не считать ошибкой уже существующую папку |

### JSON успеха

```json
{
  "ok": true,
  "operation": "mkdir",
  "result": {
    "remote_path": "/Hermes/private/reports",
    "created": true
  }
}
```

---

## 10. Команда `upload` ⬆️

Загружает локальный файл в Облако приватно.

### Вызов

```bash
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
```

### Опции

| Флаг | Значения | Назначение |
|---|---|---|
| `--overwrite` | `never`, `always`, `if-newer` | политика конфликта |
| `--mkdirs` | bool | создать родительские папки |
| `--max-size` | size | ограничить размер |
| `--checksum` | bool | проверять checksum, если возможно |

### JSON успеха

```json
{
  "ok": true,
  "operation": "upload",
  "result": {
    "local_path": "./report.pdf",
    "remote_path": "/Hermes/private/report.pdf",
    "published": false,
    "bytes": 18420
  }
}
```

---

## 11. Команда `download` ⬇️

Скачивает файл из Облака.

### Вызов

```bash
hermes-mailcloud download /Hermes/private/report.pdf ./report.pdf --json
```

### Опции

| Флаг | Значения | Назначение |
|---|---|---|
| `--overwrite` | `never`, `always`, `if-newer` | политика конфликта |
| `--checksum` | bool | проверка после скачивания |

---

## 12. Команда `mv` 🔀

Перемещает или переименовывает объект.

### Вызов

```bash
hermes-mailcloud mv /Hermes/private/a.txt /Hermes/private/b.txt --json
```

### JSON успеха

```json
{
  "ok": true,
  "operation": "mv",
  "result": {
    "source_path": "/Hermes/private/a.txt",
    "target_path": "/Hermes/private/b.txt"
  }
}
```

---

## 13. Команда `cp` 📋

Копирует объект.

### Вызов

```bash
hermes-mailcloud cp /Hermes/private/a.txt /Hermes/private/a-copy.txt --json
```

---

## 14. Команда `rm` 🗑️

Удаляет файл или папку.

### Вызов

```bash
hermes-mailcloud rm /Hermes/private/old.txt --json --yes
```

### Опции

| Флаг | Назначение |
|---|---|
| `--recursive` | удалить папку рекурсивно |
| `--yes` | обязательное подтверждение для JSON-режима |
| `--dry-run` | показать план удаления |

### Ошибка без `--yes`

```json
{
  "ok": false,
  "operation": "rm",
  "error": {
    "kind": "confirmation_required",
    "message": "rm requires --yes in non-interactive or JSON mode.",
    "exit_code": 9
  }
}
```

---

## 15. Команда `publish` 🔗

Загружает файл и создаёт публичную ссылку.

### Вызов

```bash
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

### Порядок действий

```text
validate local file
validate remote path inside public_root
validate dangerous file patterns
upload via rclone copyto
create public link via rclone link
parse public URL
record link in journal
return JSON
```

### Опции

| Флаг | Значения | Назначение |
|---|---|---|
| `--overwrite` | `never`, `always`, `if-newer` | политика конфликта |
| `--probe-url` | bool | bounded URL probe; URL remains owner-private capability data |

`publish` requires `--yes` unless it is `--dry-run`. Its normalized remote
path must be a descendant of the fixed `/Hermes/public` root. v0.1 has no
`--allow-outside-public-root` escape hatch and no expiration option.

### JSON успеха

```json
{
  "ok": true,
  "operation": "publish",
  "result": {
    "local_path": "./report.pdf",
    "remote_path": "/Hermes/public/report.pdf",
    "public_url_fingerprint": "sha256:example-public-link",
    "published": true,
    "backend": "rclone"
  },
  "warnings": []
}
```

---

## 16. Команда `link` 🔗

Создаёт или получает публичную ссылку для уже загруженного файла/папки.

### Вызов

```bash
hermes-mailcloud link /Hermes/public/report.pdf --json
```

### Опции

| Флаг | Назначение |
|---|---|
| `--probe-url` | bounded URL probe; URL remains owner-private capability data |

`link` accepts only a normalized descendant of `/Hermes/public`. It has no
v0.1 public-root override.

### JSON успеха

```json
{
  "ok": true,
  "operation": "link",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "public_url_fingerprint": "sha256:example-public-link",
    "backend": "rclone"
  }
}
```

---

## 17. Conditional capability: `unlink` (not a baseline v0.1 command) 🔒

`unlink` is deliberately absent from the baseline CLI, batch schema and help.
It may be added only after a bounded live run proves that `rclone link
--unlink` invalidates the generated public URL. Failure, an unchanged URL, or
an inconclusive probe means `unsupported`; it does not permit a private-API
fallback in v0.1.

### Вызов после post-v0.1 capability gate

```bash
hermes-mailcloud unlink "https://cloud.mail.ru/public/..." --json --yes
```

### Опции

| Флаг | Значения | Назначение |
|---|---|---|
| `--backend` | `rclone` | only after its own successful invalidation proof |
| `--yes` | bool | обязательное подтверждение |
| `--probe-after` | bool | проверить, что ссылка закрылась |

### Status

This illustrative invocation is not a v0.1 public contract. A missing proof
means no command is shipped, rather than a command that guesses or falls back.

---

## 18. Post-v0.1 proposal: `resolve` 🧭

Проверяет публичную ссылку и пытается определить режим скачивания. This is
documentation of a later proposal, not a v0.1 command.

### Вызов

```bash
hermes-mailcloud resolve "https://cloud.mail.ru/public/..." --json
```

### JSON успеха

<!-- hmc-json-example: non-contract -->
```json
{
  "ok": true,
  "operation": "resolve",
  "result": {
    "public_url_fingerprint": "sha256:example-public-link",
    "http_accessible": true,
    "content_type": "text/html",
    "direct_download_url": null,
    "download_mode": "browser_page"
  }
}
```

---

## 19. Post-v0.1 proposal: `sync` 🔄

Синхронизирует локальную и удалённую директорию. This is not a v0.1 command
or batch operation.

### Вызов

```bash
hermes-mailcloud sync push ./export /Hermes/private/export --json
hermes-mailcloud sync pull /Hermes/private/export ./export --json
```

### Опции

| Флаг | Назначение |
|---|---|
| `--delete` | удалять лишние файлы на целевой стороне |
| `--dry-run` | показать план |
| `--yes` | обязательно для `--delete` |
| `--exclude` | исключения |
| `--include` | включения |

---

## 20. Команда `batch` 🤖

Выполняет JSON-план операций.

### Вызов

```bash
hermes-mailcloud batch plan.json --json --dry-run
hermes-mailcloud batch plan.json --json --yes
```

### Пример плана

<!-- hmc-json-example: batch-plan -->
```json
{
  "version": 1,
  "defaults": {
    "overwrite": "never",
    "continue_on_error": false
  },
  "operations": [
    {
      "op": "mkdir",
      "remote_path": "/Hermes/public/reports"
    },
    {
      "op": "publish",
      "local_path": "./report.pdf",
      "remote_path": "/Hermes/public/reports/report.pdf"
    }
  ]
}
```

`batch --dry-run` validates paths and policy without rclone calls, journal
writes, URL probes or mutations; it does not need `--yes`. A batch with any
write operation requires `--yes` when executed. All operation outputs live at
`result.items`. A partial execution returns process exit `11` with `ok: false`,
`result.status: "partial_failure"`, and no top-level `error`; each item has
exactly one of its own `result` or `error`.

### JSON успеха

```json
{
  "ok": true,
  "operation": "batch",
  "result": {
    "status": "completed",
    "total": 2,
    "succeeded": 2,
    "failed": 0,
    "items": [
      {
        "index": 0,
        "ok": true,
        "operation": "mkdir",
        "result": {"remote_path": "/Hermes/public/reports"}
      },
      {
        "index": 1,
        "ok": true,
        "operation": "publish",
        "result": {
          "remote_path": "/Hermes/public/reports/report.pdf",
          "public_url_fingerprint": "sha256:example-public-link"
        }
      }
    ]
  }
}
```

---

## 21. Error kinds 🧯

Стабильный список ошибок:

```text
invalid_arguments
config_error
rclone_not_found
remote_not_configured
access_denied
not_found
conflict
unsafe_public_path
dangerous_file_pattern
confirmation_required
backend_unsupported
network_error
retry_exhausted
timeout
parse_error
unknown_error
```

---

## 22. Инварианты для агентов 🧠

Агент должен соблюдать:

```text
Всегда использовать --json.
Перед batch write запускать --dry-run.
Для publish и write-batch использовать --yes только после проверки плана.
Не публиковать файлы вне /Hermes/public.
Не передавать пароль через аргументы CLI.
Не парсить human-output.
Опираться только на ok/result/error.
```
