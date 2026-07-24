# 01. Architecture — Hermes MailCloud

<!-- hmc-json-example-default: non-contract -->

> [!important]
> **Contract freeze (2026-07-24):** the v0.1 public command set is `doctor`,
> `ls`, `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`,
> `link`, and `batch`. `unlink` needs a bounded live invalidation proof;
> `sync`, `resolve`, private API, expire/password links and full link audit are
> post-v0.1. `auth` remains configuration readiness, not a command. Older
> architecture options below are proposals, not current CLI behavior.

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`  
> Назначение: описать архитектуру агентской CLI-утилиты для Mail.ru Cloud.

---

## 1. Цель архитектуры 🧭

`hermes-mailcloud` — это не “ещё один облачный клиент”. Это агентский CLI-инструмент для Гермеса.

Главная цель:

```text
Дать агенту безопасный, предсказуемый и JSON-совместимый способ работать с Mail.ru Cloud.
```

Утилита должна уметь:

```text
загружать файлы
скачивать файлы
управлять папками
создавать публичные ссылки
возвращать стабильный JSON
защищать пользователя от случайной публикации личных данных
```

---

## 2. Архитектурный принцип 🧱

Проект строится слоями:

```mermaid
flowchart LR
    A[Hermes Agent] --> B[hermes-mailcloud CLI]
    B --> C[Command Layer]
    C --> D[Policy Layer]
    D --> E[Backend Layer]
    E --> F[Rclone Subprocess]
    E --> G[Private API post-v0.1]
    E --> H[WebDAV Optional]
    F --> I[Mail.ru Cloud]
    G --> I
    H --> I
```

Главное правило:

```text
v0.1 не реализует собственный Mail.ru Cloud API-клиент.
v0.1 управляет rclone как внешним backend-ом.
```

---

## 3. Почему rclone subprocess first 🛠️

### Причины

| Причина | Объяснение |
|---|---|
| Mail.ru backend уже существует | не надо писать файловый backend с нуля |
| Public links уже поддержаны | `rclone link` закрывает MVP |
| rclone живой проект | меньше риска, чем у старых reverse-engineered клиентов |
| subprocess проще RC-сервера | меньше surface area и проблем безопасности |
| проще тестировать fake-first | можно мокать команды и stdout |
| меньше лицензионных рисков | rclone вызывается как внешний бинарник |

### Не используем в v0.1

```text
rclone RC server
vendored rclone binary
fork rclone
native Go plugin
полный private API client
```

Rclone RC можно добавить позже, если понадобится высокая производительность при большом количестве операций.

---

## 4. Слои системы 🧩

### 4.1 CLI Layer

Отвечает за:

```text
парсинг аргументов
глобальные флаги
команды
help
exit codes
выбор JSON/human output
```

Рекомендуемый стек:

```text
Python 3.12+
Typer
Rich только для human-output, не для JSON
```

### 4.2 Command Layer

Команды проекта:

```text
doctor
ls
stat
mkdir
upload
download
mv
cp
rm
publish
link
batch
```

`auth` is configuration readiness handled by `doctor`, not a command. `unlink`
is conditional on live unlink-plus-invalidation evidence. `sync` and `resolve`
are post-v0.1 proposals, not command-layer members for this release.

Command Layer не должен знать детали rclone. Он должен вызывать абстрактный backend.

---

### 4.3 Policy Layer

Отвечает за безопасность.

Правила:

```text
publish только внутри /Hermes/public
rm требует --yes
publish и batch write operations требуют --yes
опасные файлы нельзя публиковать
секреты не попадают в stdout/stderr/logs
```

Policy Layer должен работать до backend-операций.

Пример:

```text
publish ./secret.env /Hermes/public/secret.env
→ error: dangerous_file_pattern
```

---

### 4.4 Backend Layer

Backend Layer скрывает способ выполнения операций.

В v0.1 основной backend:

```text
RcloneBackend
```

Плановые backend-и:

```text
RcloneBackend      v0.1
PrivateApiBackend  v0.2+
WebDavBackend      v0.3+
```

---

### 4.5 Rclone Runner

Минимальный интерфейс:

```python
class RcloneRunner:
    def run(self, args: list[str], timeout: int | None = None) -> RcloneResult:
        ...
```

`RcloneResult`:

```json
{
  "returncode": 0,
  "stdout": "...",
  "stderr": "...",
  "duration_ms": 1200
}
```

Runner не должен напрямую печатать в консоль.

---

### 4.6 Output Layer

Все команды должны возвращать единый envelope.

Успех:

```json
{
  "ok": true,
  "operation": "publish",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "public_url_fingerprint": "sha256:example-public-link"
  },
  "warnings": []
}
```

Ошибка:

```json
{
  "ok": false,
  "operation": "publish",
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

## 5. Предлагаемая структура проекта 📁

```text
hermes-mailcloud/
├── README.md
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── docs/
│   ├── 00-research-summary.md
│   ├── 01-architecture.md
│   ├── 02-command-contract.md
│   ├── 03-development-plan.md
│   ├── 04-probe-plan.md
│   ├── 05-safety-model.md
│   ├── 06-testing-strategy.md
│   ├── 07-agent-integration.md
│   ├── 08-configuration-and-secrets.md
│   ├── 09-known-risks.md
│   └── adr/
├── schemas/
│   ├── result-envelope.schema.json
│   ├── batch-plan.schema.json
│   └── doctor-report.schema.json
├── scripts/
│   └── probes/
│       ├── 00_env_probe.py
│       ├── 01_file_ops_probe.py
│       ├── 02_publish_probe.py
│       └── 03_unlink_probe.py
├── src/
│   └── hermes_mailcloud/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── core/
│       │   ├── errors.py
│       │   ├── result.py
│       │   ├── paths.py
│       │   └── policy.py
│       ├── rclone/
│       │   ├── runner.py
│       │   ├── parser.py
│       │   └── backend.py
│       ├── commands/
│       │   ├── doctor.py
│       │   ├── files.py
│       │   ├── publish.py
│       │   └── batch.py
│       └── output.py
└── tests/
    ├── unit/
    ├── integration/
    ├── golden/
    └── live/
```

---

## 6. Runtime dependencies ⚙️

### Required

```text
Python 3.12+
rclone
Mail.ru account
Mail.ru app password
configured rclone remote
```

### Python dependencies

```text
typer
pydantic
pydantic-settings optional
rich optional
pytest
```

### Optional later

```text
httpx
tenacity
jsonschema
keyring
```

---

## 7. Конфигурация 🔧

Файл:

```text
~/.config/hermes-mailcloud/config.toml
```

Пример:

```toml
[profiles.default]
remote = "mailru:"
rclone_path = "rclone"

private_root = "/Hermes/private"
public_root = "/Hermes/public"
# explicit doctor --live uses a fresh /TEST/<unique-run-id>/ descendant

default_overwrite = "never"
probe_public_url = true
deny_dangerous_publish = true

links_journal = "~/.local/share/hermes-mailcloud/links.jsonl"
```

Пароли не хранятся в конфиге `hermes-mailcloud`.

Credentials остаются в:

```text
rclone config
```

или передаются внешним секретным механизмом окружения.

---

## 8. Backend mapping 🗺️

| Операция | v0.1 backend | Команда rclone |
|---|---|---|
| list | rclone | `rclone lsjson remote:path` |
| stat | rclone | `rclone lsjson remote:path --stat` или parent lookup |
| mkdir | rclone | `rclone mkdir remote:path` |
| upload | rclone | `rclone copyto local remote:path` |
| download | rclone | `rclone copyto remote:path local` |
| mv | rclone | `rclone moveto remote:old remote:new` |
| cp | rclone | `rclone copyto remote:old remote:new` |
| rm file | rclone | `rclone deletefile remote:path` |
| rm dir | rclone | `rclone purge remote:path` with safety gates |
| link | rclone | `rclone link remote:path` |
| publish | rclone | `copyto` + `link` |
| unlink | conditional after live proof | `rclone link --unlink` only; no private API fallback in v0.1 |

---

## 9. Safety gates 🔐

### 9.1 Public root gate

Публикация разрешена только внутри:

```text
/Hermes/public
```

Пример ошибки:

```json
{
  "ok": false,
  "operation": "publish",
  "error": {
    "kind": "unsafe_public_path",
    "message": "Publishing outside /Hermes/public is blocked by policy.",
    "exit_code": 9
  }
}
```

### 9.2 Confirmation gate

Опасные операции требуют `--yes`:

```text
rm
publish
batch write operations
```

### 9.3 Dangerous file gate

Запрещённые имена для публикации:

```text
.env
*.env
*.key
*.pem
*.p12
*.db
cookies*
tokens*
secrets*
id_rsa*
```

---

## 10. Error model 🧯

Базовые `error.kind`:

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

`partial_failure` is a batch result status with process exit `11`, not an
`error.kind`.

---

## 11. Почему не форк rclone в v0.1 🧠

Форк rclone не нужен на первом этапе, потому что:

```text
rclone уже умеет основной сценарий
subprocess даёт быстрый MVP
форк добавит поддержку upstream, сборки, CI, релизы
нужно сначала доказать операции live-probe-скриптами
```

Форк допустим позже, если:

```text
найден баг в Mail.ru backend
нужна поддержка unlink/expire в backend
нужно изменить public link implementation
изменение стоит upstream PR
```

---

## 12. Архитектурные решения v0.1 ✅

| Решение | Статус |
|---|---|
| Python + Typer | принято |
| rclone subprocess | принято |
| JSON-first | принято |
| publish только через public root | принято |
| private API не в v0.1 core | принято |
| live-probe до private API | принято |
| не копировать GPL-код | принято |
| WebDAV не основной backend v0.1 | принято |

---

## 13. Итог 🏁

Архитектура v0.1 должна быть простой:

```text
CLI → Policy → RcloneRunner → JSON output
```

Всё остальное добавляется только после probe-доказательств.

Главная идея:

```text
Не строить идеальный облачный клиент.
Построить надёжный агентский инструмент.
```
