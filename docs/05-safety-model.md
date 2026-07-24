# 05. Safety Model: безопасная работа агента с Облаком Mail.ru 🔐

<!-- hmc-json-example-default: result-envelope -->

> [!important]
> **Frozen v0.1 safety contract (2026-07-24):** `publish` and `link` accept
> only normalized descendants of the fixed `/Hermes/public` root; v0.1 has no
> `--allow-outside-public-root` or `--allow-dangerous-file` escape hatch.
> `publish` and executing write-batch require `--yes`; dry-run is side-effect
> free. All project-owned live tests mutate only `/TEST/<run-id>/` descendants,
> while existing data outside `/TEST` is metadata/list-only. Older suggestions
> below must be read as superseded design history.

> [!important]
> Этот документ фиксирует правила безопасности для `hermes-mailcloud`. Главный принцип: агент должен уметь работать автономно, но не должен случайно публиковать личные данные, удалять файлы или светить секреты в логах.

## 1. Цель модели безопасности 🧭

`hermes-mailcloud` проектируется не как пользовательский файловый менеджер, а как CLI для агентов. У агента нет человеческой интуиции, поэтому опасные действия должны быть ограничены политиками, флагами и предсказуемыми ошибками.

Основные риски:

```text
случайная публикация личных файлов
случайное удаление файлов
утечка app password / token / cookies
публикация .env, ключей, баз данных
массовая синхронизация не туда
невозможность понять, какие ссылки были созданы
```

## 2. Принципы безопасности 🧱

| Принцип | Решение |
|---|---|
| Приватность по умолчанию | `upload` никогда не создаёт public link |
| Явная публикация | ссылка создаётся только через `publish` или `link` |
| Зона публикации | по умолчанию только `/Hermes/public` |
| Явное подтверждение | `rm`, `publish` и write-batch требуют `--yes` |
| Машинная предсказуемость | в `--json` режиме нет интерактива |
| Минимум секретов | пароли и токены не пишутся в stdout/stderr/logs |
| Проверяемость | все public links пишутся в локальный журнал |

## 3. Корневые зоны в облаке 📁

Рекомендуемая структура:

```text
/Hermes/
  private/     # приватные файлы, обычные upload/download
  public/      # файлы, которые можно публиковать
  .tmp/        # временные файлы
  .doctor/     # probe/doctor файлы
  archive/     # опционально, ручная зона архива
```

| Зона | Назначение | Публикация |
|---|---|---:|
| `/Hermes/private` | рабочие приватные файлы | запрещена |
| `/Hermes/public` | файлы для ссылок | разрешена |
| `/Hermes/.tmp` | временные файлы | запрещена |
| `/TEST/<unique-run-id>` | isolated live-test objects | never an existing-data root |
| `/Hermes/archive` | ручной архив | запрещена по умолчанию |

## 4. Правила публикации 🔗

### 4.1. `upload` всегда приватный

```bash
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
```

Эта команда не должна создавать публичную ссылку ни при каких условиях.

### 4.2. `publish` только в public root

```bash
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

Если путь вне `/Hermes/public`, команда должна упасть:

```json
{
  "ok": false,
  "operation": "publish",
  "error": {
    "kind": "unsafe_public_path",
    "message": "Publishing is allowed only inside /Hermes/public by default.",
    "exit_code": 9
  }
}
```

### 4.3. Нет escape hatch в v0.1

`publish` and `link` reject every normalized path outside `/Hermes/public`.
There is no v0.1 CLI or batch override for a human, agent, or profile.

## 5. Запрещённые к публикации файлы 🚫

По умолчанию `publish` и `link` должны блокировать опасные имена и расширения.

```text
.env
.env.*
*.key
*.pem
*.p12
*.pfx
*.kdbx
*.sqlite
*.db
cookies*
tokens*
secrets*
credentials*
id_rsa
id_ed25519
```

Пример ошибки:

```json
{
  "ok": false,
  "operation": "publish",
  "error": {
    "kind": "dangerous_file_pattern",
    "message": "This file name is blocked by publish safety policy.",
    "details": {
      "local_path": "./.env",
      "matched_rule": ".env"
    },
    "exit_code": 9
  }
}
```

> [!note]
> v0.1 has no `--allow-dangerous-file` flag. A blocked dangerous filename stays
> blocked and returns a typed policy error.

## 6. Удаление и разрушительные действия 🧨

| Команда | Риск | Требование |
|---|---|---|
| `rm file` | удалить файл | `--yes` в JSON-режиме |
| `rm folder` | удалить папку | `--recursive --yes` |
| `sync --delete` | post-v0.1 historical proposal | not a v0.1 command |
| `unlink` | conditional capability | absent until unlink/invalidation proof |
| `purge` | удалить папку целиком | не включать в v0.1 как публичную команду |

Пример:

```bash
hermes-mailcloud rm /Hermes/private/old.txt --json
```

Ответ:

```json
{
  "ok": false,
  "operation": "rm",
  "error": {
    "kind": "confirmation_required",
    "message": "Destructive operation requires --yes in JSON mode.",
    "exit_code": 9
  }
}
```

## 7. Dry-run как обязательный контур 🧪

Все пишущие команды должны поддерживать `--dry-run`.

```bash
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --dry-run
```

Ответ:

```json
{
  "ok": true,
  "operation": "publish",
  "result": {
    "dry_run": true,
    "plan": [
      {"step": "validate_local_file", "status": "planned"},
      {"step": "validate_public_root", "status": "planned"},
      {"step": "upload", "status": "planned"},
      {"step": "create_public_link", "status": "planned"}
    ]
  }
}
```

## 8. Секреты и логи 🕵️

Запрещено писать в stdout/stderr/logs:

```text
app password
OAuth access_token
CSRF token
cookies
полный rclone config
Authorization headers
```

Разрешено писать only after sanitization:

```text
имя remote
версию rclone
remote path
обрезанный stderr без секретов
```

Функция sanitization должна проходить тесты на строки:

```text
access_token=abc123
Authorization: Bearer abc123
Password=my-secret
Cookie=session=abc123
```

## 9. Журнал публичных ссылок 🧾

Каждая созданная ссылка creates a minimal local JSONL journal record. The
journal is owner-private capability data, not a cloud source of truth.

Путь по умолчанию:

```text
~/.local/share/hermes-mailcloud/links.jsonl
```

Windows-вариант:

```text
%LOCALAPPDATA%\hermes-mailcloud\links.jsonl
```

Формат строки:

<!-- hmc-json-example: non-contract -->
```json
{"ts":"2026-07-24T13:00:00Z","operation":"publish","remote_path":"/Hermes/public/report.pdf","public_url_fingerprint":"sha256:...","trace_id":"..."}
```

Журнал нужен для:

```text
локальной ревизии опубликованных путей
correlation with owner-private output
```

## 10. Batch safety 🤖

`batch` должен быть особенно строгим.

Правила:

```text
batch --dry-run должен работать без --yes
batch с пишущими операциями требует --yes
batch не должен продолжать выполнение после critical error, если не указан --continue-on-error
batch должен возвращать `result.items` по каждой операции
batch не должен скрывать partial failure
```

Пример policy error:

```json
{
  "ok": false,
  "operation": "batch",
  "error": {
    "kind": "confirmation_required",
    "message": "Batch contains write operations and requires --yes.",
    "exit_code": 9
  }
}
```

## 11. Public URL и download URL 🌐

Публичная ссылка Mail.ru Cloud не обязана быть прямой ссылкой на файл.

В v0.1 различаем:

| Поле | Значение |
|---|---|
| `public_url` | ссылка вида `https://cloud.mail.ru/public/...` |
| `download_url` | прямая ссылка на скачивание, если удалось получить |
| `download_mode` | `browser_page`, `direct`, `unknown` |

`publish` обязан вернуть `public_url`. `download_url` не является обязательным для v0.1.

## 12. Тесты безопасности 🧪

Обязательные тесты:

```text
publish вне /Hermes/public запрещён
publish .env запрещён
publish *.pem запрещён
rm без --yes запрещён
batch write без --yes запрещён
--json не задаёт интерактивных вопросов
stdout не содержит token/password/cookie
stderr sanitization работает
```

## 13. Acceptance criteria ✅

Safety model считается внедрённой, если:

```text
все опасные команды имеют policy checks
все policy errors возвращают стабильный JSON
опасные файлы блокируются
публикация ограничена public root
секреты не попадают в логи
links journal создаётся при publish/link
unit-тесты покрывают негативные сценарии
```

## 14. Источники и ориентиры 📚

- Mail.ru публичные ссылки: https://help.mail.ru/cloud/actions/share/
- Mail.ru лимит ссылок: https://help.mail.ru/cloud/faq/share/
- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
