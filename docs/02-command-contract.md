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
> Explicit dependency `setup` is additionally implemented; it does not configure
> cloud access or add a cloud operation to this frozen surface.
> The source tree implements `version`, `doctor`, `ls`, `stat`, `mkdir`, `upload`,
> `download`, `mv`, `cp`, `rm`, `publish`, `link`, and `batch`. `doctor` defaults
> to read-only readiness checks; its explicitly confirmed live mode uses only
> generated `/TEST` roots. `batch` strictly validates its version-1 discriminated
> JSON plan before backend use. Each command section below states any narrower
> implementation boundary.

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
| `--trace-id` | text | none | caller-supplied operation correlation id |
| `--dry-run` | bool | false | показать план без выполнения |
| `--yes` | bool | false | подтвердить опасную операцию |
| `--timeout` | int | 60 | timeout в секундах |
| `--retries` | int | 0 | only safe read-only work retries automatically; writes do not in v0.1 |
| `--no-color` | bool | false | отключить ANSI-цвета |

---

## 3.1. Команда `version`

`hermes-mailcloud version` prints the installed package version without loading
configuration or calling rclone. With `--json`, it returns a normal result
envelope whose `result.version` contains the same value.

---

## 3.2. Команда `setup`

После установки Python-пакета агент явно запускает `hermes-mailcloud --json setup`.
Команда подготавливает только rclone для текущего пользователя, без cloud/account
configuration, изменения PATH или бинарника внутри wheel. При отсутствии
explicit override и внешнего rclone она получает закреплённый official HTTPS
архив, проверяет SHA-256/размер архива и executable до исполнения, затем активирует
управляемую копию. Уже рабочая external/managed копия сохраняется без auto-update.
Ошибочный explicit `HMC_RCLONE_PATH`/profile `rclone_path` не обходится fallback.

```console
hermes-mailcloud --json setup
hermes-mailcloud --json setup --archive /absolute/path/to/pinned-official.zip
hermes-mailcloud --json setup --dry-run
```

`--archive` — локальный официальный архив для текущей платформы с теми же
packaged pins, не произвольный URL. `--dry-run` не скачивает, не запускает rclone
и не создаёт managed directories. Остальные команды не выполняют скрытый setup.
Поддерживаемые targets/storage и offline procedure:
[Prepare rclone](11-local-installation.md#prepare-rclone).

Успешный результат ограничен `setupResult` в нормативной envelope schema:

```json
{
  "ok": true,
  "operation": "setup",
  "result": {
    "dependency": "rclone",
    "status": "installed",
    "source": "managed",
    "version": "v1.75.2",
    "cloud_configured": false
  }
}
```

`status` также бывает `already_available` или `dry_run`; `source` — `managed`
либо `external`. Для dry-run explicit executable `version` может быть `null`,
поскольку процесс не запускается. Ошибки используют прежние kinds/exit codes,
включая `rclone_not_found` для отсутствующего explicit executable. Read-only
`doctor` только сообщает readiness/следующий шаг, но не устанавливает зависимость.

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

`doctor --json` is read-only: it resolves the non-secret profile, calls `rclone
version`, then `listremotes` only when rclone is available, and calls the
independent `lsd <remote>` and `about <remote>` checks only when the configured
remote is listed. It never creates an object or calls link/unlink. `doctor --json
--live --yes` is the explicit mutating mode; `--live` without `--yes` fails before
config or backend access. A live run allocates fresh
generated `/TEST/hermes-mailcloud-*` roots only after read-only readiness passes,
records those roots, and cleans up only same-run objects. Existing objects outside
`/TEST` remain metadata/list-only.

### JSON успеха: read-only mode

<!-- hmc-json-example: doctor-report -->
```json
{
  "ok": true,
  "operation": "doctor",
  "result": {
    "mode": "read_only",
    "checks": {
      "config_loaded": true,
      "rclone_installed": true,
      "rclone_version": "1.74.3",
      "remote_configured": true,
      "remote_listed": true,
      "cloud_access": true,
      "about_available": true
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
checks. Capability values are distinct: `supported` is positive evidence,
`unsupported` is a provider-level negative result (for unlink, either an explicit
unsupported response or a successful unlink command without URL invalidation),
`failed` is an attempted but inconclusive error, and `unknown` was not attempted.
`unlink` becomes `supported` only after the same live run proves URL invalidation;
otherwise it remains absent from the CLI. `cleanup: true` means every root created
by this run was read back as removed; a failed cleanup is reported rather than
widened to adjacent data.

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
    "hashes": {
      "MD5": "..."
    }
  }
}
```

`stat` requests rclone hash metadata, but the `hashes` object is present only
when the configured backend returns validated non-empty values. Its absence is
an explicit capability limitation, not a failed command.

---

## 9. Команда `mkdir` 📂

Создаёт папку в Облаке.

### Вызов

```bash
hermes-mailcloud mkdir /Hermes/private/reports --json
```

### Опции

v0.1 passes the normalized path to `rclone mkdir`; it has no separate
`--parents` or `--exist-ok` CLI options. The backend's documented mkdir
semantics determine parent/existing-directory handling.

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

`mkdir --dry-run` returns the normalized `remote_path`, `dry_run: true`, and a
planned validation/execution sequence without starting rclone or changing cloud
state. `created: true` records a successful rclone mkdir invocation; it does
not claim that the path was absent immediately before that invocation.

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

The implemented v0.1 slice accepts `--overwrite`; `--mkdirs`, `--max-size`,
and `--checksum` remain planned rather than silently ignored. The effective
overwrite mode is the explicit option or the profile's `default_overwrite`:

| Mode | rclone behavior |
|---|---|
| `never` | uses `--immutable`, preserving a changed destination and surfacing the backend conflict |
| `always` | uses `--ignore-times`, transferring unconditionally |
| `if-newer` | uses `--update`, preserving a newer destination |

`upload` creates no public link and never returns a URL. It invokes only
`rclone copyto`; `published` is always `false` for this command.

### JSON успеха

```json
{
  "ok": true,
  "operation": "upload",
  "result": {
    "local_path": "./report.pdf",
    "remote_path": "/Hermes/private/report.pdf",
    "published": false,
    "bytes": 18420,
    "overwrite": "never"
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

The implemented v0.1 slice accepts `--overwrite`; `--checksum` remains planned
rather than silently ignored. Download writes to a unique temporary sibling of
the requested local target. Only after rclone has succeeded is that temporary
file committed: `never` rejects an existing local target, `always` replaces it,
and `if-newer` replaces it only when the downloaded file is newer. A rclone
failure or timeout attempts to clean up the temporary file and leaves an existing target
unchanged.

### JSON успеха

```json
{
  "ok": true,
  "operation": "download",
  "result": {
    "remote_path": "/Hermes/private/report.pdf",
    "local_path": "./report.pdf",
    "bytes": 18420,
    "updated": true,
    "overwrite": "never"
  }
}
```

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

`mv` and `cp` accept `--overwrite` with the same `never`, `always`, and
`if-newer` semantics as upload. They normalize both remote paths, reject a
source equal to its target, make no automatic write retry, and invoke one
`rclone moveto` or `rclone copyto` command respectively.

---

## 13. Команда `cp` 📋

Копирует объект.

### Вызов

```bash
hermes-mailcloud cp /Hermes/private/a.txt /Hermes/private/a-copy.txt --json
```

`cp` has the same overwrite and no-retry behavior as `mv`.

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

`rm` is permanently destructive. Every real invocation requires `--yes`; a
dry-run still validates the normalized target but never starts rclone. Exact
protected targets are rejected before the backend: `/`, `/TEST`, `/Hermes`, and
the configured private, public, and temporary roots. Descendants are not made
safe merely by this guard: callers remain responsible for choosing an intended
path.

Without `--recursive`, the implementation invokes `rclone deletefile` and is
therefore limited to one remote file. With `--recursive`, it invokes
`rclone purge`, which removes the target and every descendant. The command does
not expose provider trash, recycle-bin, restore, or retention semantics and
returns no recoverable-trash identifier; successful deletion must be treated as
irreversible even if a provider happens to retain data internally.

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

`publish` requires `--yes` unless it is `--dry-run`. Its normalized remote
path must be a descendant of the fixed `/Hermes/public` root. v0.1 has no
`--allow-outside-public-root` escape hatch and no expiration option. Real
execution also requires `links_journal` in the selected profile or
`HMC_LINKS_JOURNAL`. Before upload, the CLI checks that the journal location is
safe; after rclone creates the link it writes one complete JSONL record through
an owner-only, atomic local update. The private journal retains the raw public
capability for the owner; JSON output and normal diagnostics return only its
fingerprint. A journal-preparation failure occurs before any rclone call, but a
failure after a successful `rclone link` is reported without attempting an
unproven unlink rollback.

The product command does not run an HTTP URL probe. Bounded public-URL checks
remain an opt-in isolated `/TEST/<unique-run-id>/` probe workflow so the normal
CLI never sends an owner capability to diagnostics or an unbounded network path.

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
| `--dry-run` | validate policy and show the link-and-journal plan without calling rclone |

`link` accepts only a normalized descendant of `/Hermes/public`. It has no
v0.1 public-root override. It applies the same dangerous filename policy to the
existing remote object, requires the same private `links_journal` for real
execution, and returns only `public_url_fingerprint`; the raw capability is
written only to the local owner journal.

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

`batch --dry-run` validates the version-1 plan, every operation's fields, paths,
and policy without rclone calls, journal writes, URL probes, or mutations; it does
not need `--yes`. A batch with any write operation requires outer `--yes` when
executed. `defaults.continue_on_error` is `false` unless set, so execution stops
after the first failed operation; when true, later operations still run. All
attempted operation outputs live at `result.items` in input order. A partial
execution returns process exit `11` with `ok: false`, `result.status:
"partial_failure"`, and no top-level `error`; each item has exactly one of its own
`result` or `error`.

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
