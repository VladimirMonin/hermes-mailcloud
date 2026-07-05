# 02. Command Contract — Hermes MailCloud

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`  
> Назначение: зафиксировать команды, флаги, JSON-ответы и exit codes для агентской CLI-утилиты.

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
| `--retries` | int | 3 | количество повторов |
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
    "public_url": "https://cloud.mail.ru/public/..."
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
    }
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

## 6. Команда `doctor` 🩺

Проверяет готовность окружения.

### Вызов

```bash
hermes-mailcloud doctor --json
```

### Проверки

```text
rclone installed
rclone version
remote exists
rclone about
root ls
doctor folder mkdir
small upload
small download
public link create
public URL probe
unlink capability probe
cleanup
```

### JSON успеха

```json
{
  "ok": true,
  "operation": "doctor",
  "result": {
    "rclone_installed": true,
    "rclone_version": "1.74.3",
    "remote_exists": true,
    "cloud_access": true,
    "upload": true,
    "download": true,
    "publish": true,
    "public_url_probe": true,
    "unlink_supported": false,
    "cleanup": true
  },
  "warnings": [
    "unlink is not confirmed for this backend; private-api fallback may be required"
  ]
}
```

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
    "message": "rm requires --yes in non-interactive or JSON mode."
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
| `--public-root` | path | разрешённая зона публикации |
| `--allow-outside-public-root` | bool | отключить защиту |
| `--overwrite` | `never`, `always`, `if-newer` | политика конфликта |
| `--probe-url` | bool | проверить ссылку HTTP-запросом |
| `--record-link` | bool | записать ссылку в журнал |
| `--expire` | duration | best-effort, не гарантируется |
| `--download-check` | `none`, `head`, `get-small` | проверка публичной ссылки |

### JSON успеха

```json
{
  "ok": true,
  "operation": "publish",
  "result": {
    "local_path": "./report.pdf",
    "remote_path": "/Hermes/public/report.pdf",
    "public_url": "https://cloud.mail.ru/public/...",
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
| `--public-root` | разрешённая зона |
| `--allow-outside-public-root` | отключить safety gate |
| `--record-link` | записать в журнал |
| `--probe-url` | проверить доступность ссылки |

### JSON успеха

```json
{
  "ok": true,
  "operation": "link",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "public_url": "https://cloud.mail.ru/public/...",
    "backend": "rclone"
  }
}
```

---

## 17. Команда `unlink` 🔒

Закрывает публичный доступ.

### Вызов

```bash
hermes-mailcloud unlink "https://cloud.mail.ru/public/..." --json --yes
```

### Опции

| Флаг | Значения | Назначение |
|---|---|---|
| `--backend` | `auto`, `rclone`, `private-api` | чем закрывать доступ |
| `--yes` | bool | обязательное подтверждение |
| `--probe-after` | bool | проверить, что ссылка закрылась |

### Статус v0.1

`unlink` должен быть реализован только после live-probe. До подтверждения команда может возвращать:

```json
{
  "ok": false,
  "operation": "unlink",
  "error": {
    "kind": "backend_unsupported",
    "message": "unlink is not confirmed for the current backend. Run doctor first."
  }
}
```

---

## 18. Команда `resolve` 🧭

Проверяет публичную ссылку и пытается определить режим скачивания.

### Вызов

```bash
hermes-mailcloud resolve "https://cloud.mail.ru/public/..." --json
```

### JSON успеха

```json
{
  "ok": true,
  "operation": "resolve",
  "result": {
    "public_url": "https://cloud.mail.ru/public/...",
    "http_accessible": true,
    "content_type": "text/html",
    "direct_download_url": null,
    "download_mode": "browser_page"
  }
}
```

---

## 19. Команда `sync` 🔄

Синхронизирует локальную и удалённую директорию.

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

```json
{
  "version": 1,
  "defaults": {
    "public_root": "/Hermes/public",
    "overwrite": "never"
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

### JSON успеха

```json
{
  "ok": true,
  "operation": "batch",
  "result": {
    "total": 2,
    "succeeded": 2,
    "failed": 0,
    "items": [
      {
        "ok": true,
        "op": "mkdir",
        "remote_path": "/Hermes/public/reports"
      },
      {
        "ok": true,
        "op": "publish",
        "remote_path": "/Hermes/public/reports/report.pdf",
        "public_url": "https://cloud.mail.ru/public/..."
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
timeout
parse_error
partial_failure
unknown_error
```

---

## 22. Инварианты для агентов 🧠

Агент должен соблюдать:

```text
Всегда использовать --json.
Перед batch write запускать --dry-run.
Для rm/unlink/sync --delete использовать --yes только после проверки плана.
Не публиковать файлы вне /Hermes/public.
Не передавать пароль через аргументы CLI.
Не парсить human-output.
Опираться только на ok/result/error.
```
