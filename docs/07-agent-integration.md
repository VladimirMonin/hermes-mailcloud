# 07. Agent Integration: интеграция hermes-mailcloud с агентами 🤖

<!-- hmc-json-example-default: result-envelope -->

> [!important]
> **Frozen v0.1 agent contract (2026-07-24):** agents use only `doctor`, `ls`,
> `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`,
> and `batch`. `unlink` appears only after live rclone unlink plus URL
> invalidation proof; `sync`, `resolve`, private API, expire/password links and
> full link audit are post-v0.1. Explicit dependency `setup` is an additional
> installation step, not a cloud/auth operation. Never put a returned public URL, raw provider
> diagnostics or a probe artifact in Git, Kanban or chat.

> [!important]
> Этот документ описывает, как агент должен вызывать `hermes-mailcloud`. CLI проектируется как инструмент для автономных задач, поэтому главный интерфейс — не человекочитаемый вывод, а стабильный JSON, exit codes и явные флаги подтверждения.

## 1. Основное правило 🧭

При использовании CLI агент вызывает команды так:

```bash
hermes-mailcloud <command> ... --json
```

Only the confirmation-gated operations require `--yes` for a real run:

```bash
rm ... --yes
publish ... --yes
batch plan.json --yes  # only when the plan has write operations
doctor --live --yes
```

`mkdir`, `upload`, `download`, `mv`, `cp`, and `link` still mutate local or
remote state, but the frozen v0.1 policy does not require `--yes` for them.
Agents should use `--dry-run` first when that mode is available and must never
assume an automatic write retry.

Для планирования агент сначала использует:

```bash
--dry-run
```

Типовой цикл:

```text
dry-run → проверить JSON plan → выполнить с обязательным для команды подтверждением → прочитать result/error
```

### Прямой Python-вызов в source-built пакете

Агент в том же Python-окружении может использовать поддерживаемый
[`MailCloudApplication`](01-architecture.md#current-in-process-application-interface)
без Typer/Click/Rich и без запуска CLI-процесса. Доступны `version`, `ls`, `stat`,
`mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, `setup`, `doctor`,
`batch(document)` и `batch_file(Path)`. Используйте эту поверхность, не внутренние
command services и не вызов CLI для каждого batch item.

```python
from hermes_mailcloud.application import CallOptions, MailCloudApplication

application = MailCloudApplication()
document = {
    "version": 1.0,
    "operations": [
        {"op": "ls", "remote_path": "/Hermes"},
        {"op": "mkdir", "remote_path": "/TEST/example-plan"},
    ],
}
planned = application.batch(document, options=CallOptions(dry_run=True))
payload = planned.to_payload()
exit_code = planned.exit_code
```

Результат уже санитизирован до доступа к его полям; API ничего не печатает и не
завершает процесс. Проверяйте `ok`/typed `error.kind`/`exit_code`, не текст ошибки.
Реальные `rm`/`publish` требуют `CallOptions(yes=True)`; standalone `link` — нет.
Все guards и private-journal правила сохраняются. Для standalone file/public writes
retry budget по умолчанию нулевой; explicit positive budget запрещён даже в dry-run. После timeout/unknown/ошибки journal
не повторяйте write автоматически: эффект мог уже состояться. Нужен readback и
решение в пределах действующих полномочий, не предполагаемый rollback.

`setup()` — явная подготовка pinned зависимости, без configured cloud remote и без
file backend; optional archive передаётся как `Path`. Для doctor live без yes
возвращается confirmation/9; live+yes+dry-run даёт invalid_arguments/2, до config.
Read-only doctor с dry-run всё равно читает backend. Проверяйте readiness fields,
не только успешность diagnostic envelope.

`batch_file(Path(...))` использует тот же parser/execution, что `batch(document)`.
Любой batch write требует outer yes; dry-run планирует все items без backend.
При exit 11 разбирайте ordered `result.items`: top-level error отсутствует, total
считает попытки, stop/continue определён defaults плана. После ordinary unexpected
item error прежние outcomes сохраняются; пакет не становится транзакцией или
безопасным для автоматического replay. Неверный UTF-8 и defaults:null — отказ/2;
version 1.0 допустим, bool/string/nonfinite не заменяют integer version.

Устанавливайте точный accepted source-built wheel в окружение consumer-а: старый `v0.1.0` release asset
не содержит этот API, а отдельный `uv tool` interpreter не добавляет imports
в Python-процесс агента. См. [границы установки](11-local-installation.md#6-development-and-updates).
Пример планирования не разрешает реальную мутацию без intent владельца.

### Подготовка после установки пакета

Агент устанавливает accepted non-editable Python package, затем явно вызывает
`hermes-mailcloud --json setup` и read-only `hermes-mailcloud --json doctor`.
Setup готовит pinned official user-scoped rclone без cloud configuration и без
ручного executable/PATH шага пользователя. Для offline archive допускается только
`setup --archive` с packaged pins; dry-run не скачивает и не запускает процесс.
Help/version/doctor/обычные file commands никогда не загружают зависимость скрыто.
Существующая рабочая external/managed копия не обновляется автоматически;
invalid explicit path требует отдельного исправления, не silent fallback.
Подробности: [Prepare rclone](11-local-installation.md#prepare-rclone).

## 2. Что агент может делать ✅

| Задача | Команда |
|---|---|
| подготовить зависимость при установке | `setup --json` (не cloud setup) |
| проверить окружение | `doctor --json` |
| посмотреть папку | `ls /path --json` |
| загрузить приватный файл | `upload local remote --json` |
| скачать файл | `download remote local --json` |
| создать папку | `mkdir remote --json` |
| переименовать/переместить | `mv old new --json` |
| опубликовать файл | `publish local remote --json --yes` |
| получить ссылку на существующий файл | `link remote --json` |
| закрыть публичный доступ | unavailable in v0.1 pending unlink proof |
| выполнить план | `batch plan.json --json --dry-run` / `--yes` |

## 3. Что агенту нельзя делать без отдельной политики 🚫

```text
предполагать несуществующий v0.1 escape hatch outside public root
предполагать несуществующий v0.1 dangerous-file override
использовать post-v0.1 sync
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
    "public_url_fingerprint": "sha256:example-public-link",
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
    },
    "exit_code": 9
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
| `4` | rclone не найден | при разрешённой подготовке вызвать `setup`; invalid explicit override исправить отдельно |
| `5` | remote не настроен | сообщить оператору |
| `6` | auth/access denied | сообщить оператору |
| `7` | объект не найден | проверить путь |
| `8` | конфликт имени | изменить overwrite policy |
| `9` | запрещённое действие | не обходить без разрешения |
| `10` | network/retry exhausted | retry only documented safe read-only work |
| `11` | partial failure | разобрать `result.items` |
| `12` | backend не поддерживает функцию | сообщить unsupported; no v0.1 private-API fallback |
| `13` | parse error | сохранить redacted diagnostic and stop |
| `14` | timeout | retry only documented safe read-only work |

## 7. Типовые сценарии 🧩

### 7.1. Загрузить файл приватно

```bash
hermes-mailcloud upload ./report.md /Hermes/private/report.md --json
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

<!-- hmc-json-example: non-contract -->
```json
{
  "public_url_fingerprint": "sha256:example-public-link"
}
```

### 7.3. Получить ссылку на уже загруженный файл

```bash
hermes-mailcloud link /Hermes/public/artifact.zip --json
```

### 7.4. Post-v0.1 proposal: проверить публичную ссылку

```bash
hermes-mailcloud resolve "https://cloud.mail.ru/public/..." --json
```

Результат может сказать, что ссылка доступна, но не является прямой download-ссылкой:

<!-- hmc-json-example: non-contract -->
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

Сначала:

```bash
hermes-mailcloud batch plan.json --json --dry-run
```

The plan is strict `version: 1` JSON: each `operations[]` item is discriminated
by `op`, so fields from one operation cannot silently apply to another. Dry-run
validates every item without launching rclone; agents can then inspect the
ordered `result.items` plan before confirming execution.

Потом:

```bash
hermes-mailcloud batch plan.json --json --yes
```

## 9. Retry policy 🔁

Only explicitly safe read-only operations may retry automatically when an error
is temporary:

```text
network_error
timeout
retry_exhausted
```

No v0.1 write operation is retried automatically. An ambiguous write side effect
must be surfaced for inspection. The agent must not retry without changing
parameters after:

```text
unsafe_public_path
dangerous_file_pattern
confirmation_required
invalid_arguments
access_denied
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
2. Для операций с поддержкой dry-run сначала использовать --dry-run.
3. Не использовать --allow-outside-public-root.
4. Не использовать --allow-dangerous-file.
5. При ok=false читать error.kind.
6. При network_error повторять только явно безопасную read-only операцию.
7. При policy error не обходить защиту без явного задания пользователя.
8. При publish сохранять returned URL only in owner-private state; shared handoffs use a fingerprint.
9. После batch проверять каждый элемент result.items.
10. Перед длинной задачей запускать doctor --json.
```

## 12. Минимальный happy path для агента ✅

```bash
hermes-mailcloud doctor --json
hermes-mailcloud publish ./result.zip /Hermes/public/result.zip --json --dry-run
hermes-mailcloud publish ./result.zip /Hermes/public/result.zip --json --yes
```

После этого агент использует:

<!-- hmc-json-example: non-contract -->
```json
{
  "public_url_fingerprint": "sha256:example-public-link"
}
```

For partial batch execution, the process exits `11`; `ok` is `false`, there is
no top-level `error`, and each per-operation outcome is at `result.items`.

## 13. Источники и ориентиры 📚

- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
- Mail.ru публичные ссылки: https://help.mail.ru/cloud/actions/share/
