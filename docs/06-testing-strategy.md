# 06. Testing Strategy: стратегия тестирования hermes-mailcloud 🧪

<!-- hmc-json-example-default: non-contract -->

> [!important]
> **Contract freeze (2026-07-24):** v0.1 schema/golden tests cover the required
> command set, strict result/error exclusivity, batch `result.items` with exit
> `11`, path/dry-run/retry/journal/redaction rules and read-only/live doctor
> modes. Any live mutation is confined to a generated `/TEST/<run-id>/`
> descendant; public URLs/raw provider output never leave owner-private local
> evidence. Text below that names other commands is historical planning.

> [!important]
> `hermes-mailcloud` работает с реальным облаком, публичными ссылками и потенциально личными файлами. Поэтому основная стратегия: максимум тестов без live-доступа, а live-тесты — только явно включённые и изолированные.

## 1. Цели тестирования 🎯

Тесты должны доказать четыре вещи:

```text
CLI отдаёт стабильный JSON
политики безопасности работают
rclone вызывается предсказуемо
live-сценарии подтверждены отдельными gated-тестами
```

Мы не должны зависеть от Mail.ru Cloud в обычном CI. Основной набор тестов обязан проходить без сети, без rclone config и без реального аккаунта.

## 2. Пирамида тестов 🧱

| Уровень | Назначение | Live-доступ | Запуск в CI |
|---|---|---:|---:|
| Unit | чистая логика, политики, модели | нет | да |
| Fake integration | CLI + fake rclone runner | нет | да |
| Golden JSON | стабильность JSON-контракта | нет | да |
| Probe scripts | проверка окружения и возможностей | да | вручную |
| Live tests | real Mail.ru Cloud only under a fresh `/TEST/<run-id>/` descendant | да | только opt-in |
| Manual smoke | проверка перед релизом | да | вручную |

## 3. Маркеры pytest 🏷️

Рекомендуемые маркеры:

```python
import pytest

pytestmark = pytest.mark.live
```

Запуск обычных тестов:

```bash
uv run pytest -q -m "not live"
```

Запуск live-тестов:

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: HMC_TEST_ROOT=/TEST/hermes-mailcloud-<unique-run-id> uv run pytest -q -m live
```

Если `HMC_LIVE` не установлен, live-тесты должны пропускаться, а не падать.

## 4. Unit tests ⚙️

Unit-тесты покрывают чистую логику.

```text
tests/unit/
  test_result_envelope.py
  test_error_model.py
  test_path_policy.py
  test_publish_policy.py
  test_deny_patterns.py
  test_secret_sanitizer.py
  test_exit_codes.py
```

### Что тестировать

| Модуль | Проверки |
|---|---|
| `core.result` | `ok/result/error/warnings` |
| `core.errors` | стабильные `error.kind` |
| `core.paths` | нормализация `/Hermes/public` |
| `core.policy` | запреты публикации |
| `core.sanitize` | вырезание token/password/cookie |
| `core.exit_codes` | mapping ошибок в exit code |

Примеры негативных проверок:

```text
/Hermes/public/../private/file.txt запрещён
./.env запрещён к publish
file.pem запрещён к publish
rm без --yes запрещён
sync --delete без --yes запрещён
```

## 5. Fake rclone runner 🧰

Реальный `subprocess.run` нельзя использовать в большинстве тестов. Нужен интерфейс:

```python
class RcloneRunner:
    def run(self, args: list[str], timeout: int | None = None) -> RcloneResult:
        ...
```

И fake-реализация:

```python
class FakeRcloneRunner:
    def __init__(self, responses: dict[tuple[str, ...], RcloneResult]):
        self.responses = responses
        self.calls = []
```

Это позволит тестировать:

```text
какие команды строятся
как парсится stdout
как ошибки rclone превращаются в JSON
что секреты не попадают в вывод
```

## 6. Golden JSON tests 📦

Golden-тесты фиксируют контракт ответа. Они особенно важны для агентов.

Структура:

```text
tests/golden/
  publish_success.json
  publish_unsafe_path_error.json
  link_success.json
  rm_confirmation_required.json
  doctor_success.json
```

Принцип:

```text
команда → JSON response → сравнить с golden snapshot
```

Поля вроде `trace_id`, `started_at`, `duration_ms` нужно либо стабилизировать fake-часами, либо исключать из сравнения.

## 7. CLI tests 🖥️

CLI-тесты запускаются через `typer.testing.CliRunner`.

Проверки:

```text
--help работает
--json возвращает JSON
ошибка аргументов даёт exit code 2
publish outside public root даёт stable error
rm без --yes падает
batch --dry-run не вызывает runner
```

Пример:

```python
def test_publish_requires_public_root(cli_runner, fake_rclone):
    result = cli_runner.invoke(app, [
        "publish",
        "./report.pdf",
        "/Hermes/private/report.pdf",
        "--json",
    ])
    assert result.exit_code == 9
    payload = json.loads(result.stdout)
    assert payload["error"]["kind"] == "unsafe_public_path"
```

## 8. Parser tests для rclone 📤

Нужно отдельно тестировать парсинг:

```text
rclone version
rclone listremotes
rclone lsjson
rclone link stdout
rclone stderr errors
```

`rclone link` должен приниматься только если найдена ссылка вида:

```text
https://cloud.mail.ru/public/...
```

Если stdout содержит мусор, команда должна вернуть ошибку:

```json
{
  "ok": false,
  "operation": "link",
  "error": {
    "kind": "parse_error",
    "message": "rclone link output did not contain a supported public-link shape",
    "exit_code": 13
  }
}
```

## 9. Live tests 🌐

Live-тесты должны использовать только test root:

```text
/TEST/<unique-run-id>
```

Запуск:

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: HMC_TEST_ROOT=/TEST/hermes-mailcloud-<unique-run-id> uv run pytest -q -m live
```

Набор:

```text
tests/live/
  test_live_env.py
  test_live_file_ops.py
  test_live_publish.py
  test_live_unlink_capability.py
```

Правила live-тестов:

```text
не трогать пользовательские папки
создавать уникальные имена файлов
всегда пытаться cleanup
не требовать unlink для прохождения MVP
не писать секреты в assert messages
```

## 10. Probe scripts vs live tests 🔍

Probe-скрипты и live-тесты похожи, но не одинаковы.

| Инструмент | Назначение |
|---|---|
| Probe scripts | ручная диагностика возможностей окружения |
| Live tests | проверка поведения реализованного кода |

Probe можно запускать до написания основного CLI. Live tests появляются после реализации модулей.

## 11. CI strategy 🤖

В обычном CI:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
```

Не запускать по умолчанию:

```text
live tests
probe scripts
реальный rclone config
private API tests
```

Опциональный workflow `manual-live.yml` может запускаться только вручную и только с секретами окружения.

## 12. Тесты безопасности 🔐

Обязательный набор:

```text
test_publish_blocks_private_root
test_publish_blocks_dotenv
test_publish_blocks_private_key
test_rm_requires_yes
test_sync_delete_requires_yes
test_batch_write_requires_yes
test_json_mode_never_prompts
test_sanitize_access_token
test_sanitize_cookie
test_sanitize_password
```

## 13. Тесты batch-режима 📚

Проверки:

```text
валидный plan проходит schema validation
неизвестная op падает
write batch без --yes падает
batch --dry-run не вызывает runner
partial failure returns `result.items` with process exit 11
continue-on-error продолжает выполнение
```

Пример partial failure:

<!-- hmc-json-example: result-envelope -->
```json
{
  "ok": false,
  "operation": "batch",
  "result": {
    "status": "partial_failure",
    "exit_code": 11,
    "total": 2,
    "succeeded": 1,
    "failed": 1,
    "items": [
      {"index": 0, "operation": "mkdir", "ok": true, "result": {}},
      {"index": 1, "operation": "publish", "ok": false, "error": {"kind": "network_error", "message": "link failed", "exit_code": 10}}
    ]
  }
}
```

## 14. Acceptance criteria для тестов ✅

К v0.1 должны выполняться условия:

```text
unit-тесты покрывают core/policy/parsers
fake integration покрывает все команды v0.1
golden JSON зафиксирован для ключевых ответов
live publish test проходит вручную
live file ops test проходит вручную
unlink capability зафиксирован как supported/unsupported
CI проходит без live-доступа
```

## 15. Источники и ориентиры 📚

- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
- Typer testing: https://typer.tiangolo.com/tutorial/testing/
- Pytest markers: https://docs.pytest.org/en/stable/example/markers.html
