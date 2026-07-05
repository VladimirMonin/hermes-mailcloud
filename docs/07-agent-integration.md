# 07. Agent Integration: интеграция hermes-mailcloud с агентами 🤖

> [!important]
> Этот документ описывает, как агент должен вызывать `hermes-mailcloud`. CLI проектируется как инструмент для автономных задач, поэтому главный интерфейс — не человекочитаемый вывод, а стабильный JSON, exit codes и явные флаги подтверждения.

## 1. Основное правило 🧭

Агент всегда вызывает команды так:

```bash
hermes-mailcloud <command> ... --json
```

Если команда меняет состояние, агент обязан явно передать:

```bash
--yes
```

Для планирования агент сначала использует:

```bash
--dry-run
```

Типовой цикл:

```text
dry-run → проверить JSON plan → выполнить с --yes → прочитать result/error
```

## 2. Что агент может делать ✅

| Задача | Команда |
|---|---|
| проверить окружение | `doctor --json` |
| посмотреть папку | `ls /path --json` |
| загрузить приватный файл | `upload local remote --json` |
| скачать файл | `download remote local --json` |
| создать папку | `mkdir remote --json --yes` |
| переименовать/переместить | `mv old new --json --yes` |
| опубликовать файл | `publish local remote --json --yes` |
| получить ссылку на существующий файл | `link remote --json --yes` |
| закрыть публичный доступ | `unlink url --json --yes` |
| выполнить план | `batch plan.json --json --dry-run` / `--yes` |

## 3. Что агенту нельзя делать без отдельной политики 🚫

```text
использовать --allow-outside-public-root
использовать --allow-dangerous-file
делать sync --delete без отдельного задания
публиковать файлы вне /Hermes/public
передавать пароли в аргументах команд
парсить человекочитаемый вывод вместо JSON
игнорировать ok=false
```

## 4. Формат успешного ответа 📦

```json
{
  "ok": true,
  "operation": "publish",
  "trace_id": "agent-task-001",
  "profile": "default",
  "remote": "mailru:",
  "result": {
    "local_path": "./artifact.zip",
    "remote_path": "/Hermes/public/artifact.zip",
    "public_url": "https://cloud.mail.ru/public/...",
    "published": true
  },
  "warnings": []
}
```

Агент должен читать:

| Поле | Что значит |
|---|---|
| `ok` | успех/ошибка |
| `operation` | какая команда выполнялась |
| `result` | результат операции |
| `warnings` | нефатальные предупреждения |
| `trace_id` | связь с задачей агента |

## 5. Формат ошибки ⚠️

```json
{
  "ok": false,
  "operation": "publish",
  "trace_id": "agent-task-001",
  "error": {
    "kind": "unsafe_public_path",
    "message": "Publishing is allowed only inside /Hermes/public by default.",
    "details": {
      "remote_path": "/Hermes/private/artifact.zip",
      "public_root": "/Hermes/public"
    }
  }
}
```

Агент должен принимать решение по `error.kind`, а не по свободному тексту `message`.

## 6. Exit codes 🚦

| Код | Значение | Реакция агента |
|---:|---|---|
| `0` | успех | читать `result` |
| `1` | неизвестная ошибка | остановить задачу |
| `2` | ошибка аргументов | исправить вызов |
| `3` | ошибка конфига | вызвать `doctor` |
| `4` | rclone не найден | сообщить оператору |
| `5` | remote не настроен | сообщить оператору |
| `6` | auth/access denied | сообщить оператору |
| `7` | объект не найден | проверить путь |
| `8` | конфликт имени | изменить overwrite policy |
| `9` | запрещённое действие | не обходить без разрешения |
| `10` | network/retry exhausted | можно повторить позже |
| `11` | partial failure | разобрать `results[]` |
| `12` | backend не поддерживает функцию | использовать fallback |

## 7. Типовые сценарии 🧩

### 7.1. Загрузить файл приватно

```bash
hermes-mailcloud upload ./report.md /Hermes/private/report.md --json --yes
```

Ожидаемый результат:

```json
{
  "ok": true,
  "operation": "upload",
  "result": {
    "local_path": "./report.md",
    "remote_path": "/Hermes/private/report.md",
    "published": false
  }
}
```

### 7.2. Загрузить файл и получить ссылку

```bash
hermes-mailcloud publish ./artifact.zip /Hermes/public/artifact.zip --json --yes
```

Агент забирает:

```json
{
  "public_url": "https://cloud.mail.ru/public/..."
}
```

### 7.3. Получить ссылку на уже загруженный файл

```bash
hermes-mailcloud link /Hermes/public/artifact.zip --json --yes
```

### 7.4. Проверить публичную ссылку

```bash
hermes-mailcloud resolve "https://cloud.mail.ru/public/..." --json
```

Результат может сказать, что ссылка доступна, но не является прямой download-ссылкой:

```json
{
  "ok": true,
  "operation": "resolve",
  "result": {
    "http_accessible": true,
    "download_mode": "browser_page",
    "direct_download_url": null
  }
}
```

## 8. Batch-сценарий 📚

Агент может передать план операций.

```json
{
  "version": 1,
  "defaults": {
    "overwrite": "never",
    "public_root": "/Hermes/public"
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

Сначала:

```bash
hermes-mailcloud batch plan.json --json --dry-run
```

Потом:

```bash
hermes-mailcloud batch plan.json --json --yes
```

## 9. Retry policy 🔁

Агент может повторить операцию, если ошибка относится к временным:

```text
network_error
timeout
retry_exhausted
rate_limited
temporary_backend_error
```

Агент не должен повторять без изменения параметров:

```text
unsafe_public_path
dangerous_file_blocked
confirmation_required
invalid_arguments
auth_failed
remote_not_configured
```

## 10. Trace ID 🧾

Агент должен передавать `--trace-id`, если задача имеет внешний идентификатор.

```bash
hermes-mailcloud publish ./artifact.zip /Hermes/public/artifact.zip --json --yes --trace-id "kanban-123"
```

Это упрощает связь:

```text
лог агента
лог hermes-mailcloud
links journal
probe/doctor reports
```

## 11. Recommended agent policy 🧠

Для Гермеса рекомендуется такой набор правил:

```text
1. Всегда использовать --json.
2. Для write-операций сначала использовать --dry-run.
3. Не использовать --allow-outside-public-root.
4. Не использовать --allow-dangerous-file.
5. При ok=false читать error.kind.
6. При network_error можно повторить операцию ограниченное число раз.
7. При policy error не обходить защиту без явного задания пользователя.
8. При publish сохранять public_url в результат задачи.
9. После batch проверять каждый элемент results[].
10. Перед длинной задачей запускать doctor --json.
```

## 12. Минимальный happy path для агента ✅

```bash
hermes-mailcloud doctor --json
hermes-mailcloud publish ./result.zip /Hermes/public/result.zip --json --dry-run
hermes-mailcloud publish ./result.zip /Hermes/public/result.zip --json --yes
```

После этого агент использует:

```json
{
  "public_url": "https://cloud.mail.ru/public/..."
}
```

## 13. Источники и ориентиры 📚

- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
- Mail.ru публичные ссылки: https://help.mail.ru/cloud/actions/share/
