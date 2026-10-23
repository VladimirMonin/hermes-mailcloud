# 06. Testing Strategy: стратегия тестирования hermes-mailcloud 🧪

## Действующие основания проверки

Эта страница остаётся единственным владельцем стратегии тестирования. Практический
порядок и команды — в [инструкции тестирования](../instructions/TEST.quality_gates.instructions.md),
политика диагностических данных — в [основах наблюдаемости](foundation/observability-policy.md).
Методика адаптирована из полного [Project Foundation Kit](../tools/project-foundation/README.md);
исторические планы ниже не становятся перечнем реализованных тестов.

Проверяем обещанное поведение, а не количество классов или процент покрытия.
Для command-first-перехода нужны два соединённых пути: прямой вызов настоящего
прикладного API без Typer и вызов того же владельца через настоящий CLI.
Текущий поддерживаемый API охватывает все shipped операции, включая `setup`,
`doctor`, `batch(document)` и `batch_file(Path)`; connected проверки находятся в
`tests/application/`. Окончательная очистка transitional glue и qualification всей
поставки остаются в [полном плане](plans/command-first-refactor.md).
Внешний rclone/облако можно заменять; сам проверяемый прикладной сценарий — нельзя.
Результаты, коды ошибок, сохранность файла/журнала, отказ до эффекта, отсутствие
повторной записи и возможность следующей операции важнее одного `mock.called`.

Изоляция устанавливается до импорта/collection: синтетические HOME/config,
RCLONE_CONFIG, журнал, backend и временные каталоги; подходящий образец — в
[CI](../.github/workflows/ci.yml). Очистка нужна и после частичного setup.
Не читаем рабочие credentials и не обращаемся к реальному remote ради обычного теста.

Полный offline-набор обоснован общим переносом границы приложения; проверка чистого
wheel/launcher нужна для изменённого поставляемого входа. Авторские проверки и
независимая приёмка разделяются. NOT_RUN, skip и выполненный отрицательный случай
имеют разный смысл. Новая правка fixture/serializer/артефакта требует затронутой
перепроверки; неизменённые доказательства используются только в их исходной области.

System/batch проверки проходят настоящий installer за synthetic pins/download/
execution seams, version/activation readback и сохранность прежних bytes; setup
не создаёт file backend и не вызывается скрыто. Для doctor проверяются strict live/
yes/dry-run admission до loader, read-only checks/warnings и real probes/HTTP/cleanup
за заменёнными внешними краями. Для обоих batch inputs нужны parser-before-config,
все discriminators/defaults, однократная composition, all-item dry-run, preflight,
ordered partial stop/continue и fixed unknown item failure без утраты прежних items.
BaseException не маскируется обычным result. Parser/schema вместе различают omitted/
null, integer 1/1.0 против bool/string/nonfinite и invalid UTF-8; ошибочное profile
metadata не должно перекрывать ранний отказ. Native-text fake download сохраняет
реальные LF/CRLF bytes источника, а не ослабляет probe assertion. SDK-blocked installed
API и uninjected launcher проверяются раздельно.

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

### Native subprocess boundary and test-only argv drivers

Переносимые subprocess integration tests используют `tests/helpers/cli_fake.py`:
дочерний Python запускает настоящие CLI/adapters/runner с fake script через
существующий Python argv prefix, без shebang/chmod и shell wrappers. Это test-only
подстановка executable argv, не новый формат `HMC_RCLONE_PATH`, не доказательство
реального rclone/Mail.ru и не проверка установленного console launcher. Последний
нужно проверять отдельно вне checkout, из clean wheel, без такой подстановки.
Локальные clean-wheel/launcher и fake-backed runtime checks выполнены на
Windows/Linux × Python 3.12/3.13. Windows evidence получено с elevation: оно не
заменяет ordinary-user qualification, реальный rclone или remote Actions GREEN.

Native Windows process tests проверяют suspended launch → Job assignment →
resume, реальные self-ready parent/descendant identities, parent exit с открытыми
pipes, timeout и startup/cleanup/pipe failures. Readiness payload должен быть
прочитан и проверен в одном конечном budget; постоянный отказ, неверная identity
или посторонняя ошибка не превращаются в readiness. Проверяются empty Job,
завершение точных child handles, EOF и освобождение ресурсов; неопределённый
cleanup не должен давать success или clean timeout. POSIX process-group проверки
сохраняются отдельно, а их platform skip не является Windows proof. Подробный
пользовательский contract — [Windows subprocess boundary](11-local-installation.md#windows-subprocess-boundary).

File-command controls сохраняют реального конкурентного победителя download
`never` (no-clobber) и проверяют `if-newer` по фактически различимым timestamps,
а не по предположению о точности часов/файловой системы. Connected API/CLI проверки
дополнительно проходят настоящие file/public owners: строгие типы, meaningful
zero-effect dry-run, profile read retries против explicit write budget, полные
байты destination и очистку своего partial temp после timeout. Public проверки
используют native private journal: preflight до cloud, fingerprint и private record
при успехе, безопасный record failure после link без retry/unlink/rollback.
Прямые данные и реальный CLI output проверяются на typed/unknown errors и отсутствие
synthetic secrets. Installed API проверяется в отдельном процессе без CLI SDK;
full provenance не импортирует CLI перед этим gate. Publish/link проверяются offline,
если действующая live authority ограничена `/TEST`: обход public-root policy ради
теста недопустим. Dry-run без backend, write-once retry policy и public/batch safety
остаются обязательными.

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

Directory `stat` может получить от rclone metadata корня с пустыми `Path` и
`Name`. Эта форма допустима только для `IsDir`, равного boolean `true`, при
пустом `Path`: в результате сохраняется запрошенный нормализованный `remote_path`.
Она не разрешает пустые имена файлов, неверные типы/пути или пустые элементы
обычного `lsjson` listing. Parser и subprocess CLI regression checks сохраняют
эти negative controls; отдельная gated live-проверка установленного launcher
подтверждает directory stat/list и file stat/download. Одна классификация
нативного provider metadata не заменяет успешный вызов приложения.

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

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) задаёт Ubuntu/Windows ×
Python 3.12/3.13. Lock/Ruff выполняются отдельно; каждая runtime cell делает locked
dev sync, offline pytest непересекающимися packs (application, core/CLI/packaging,
commands/batch, journal, parser/process), build wheel и sdist, runtime-only locked
export и clean installed smoke. Packaging control проверяет полноту module cover.
Эквивалентные основные gates (pytest в CI разделён на packs):

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
uv build
```

`scripts/smoke_installed.py` устанавливает wheel в новый runtime вне checkout:
без editable/PYTHONPATH/dev dependencies, с проверкой version, import location и
component hashes против wheel, включая Windows dependency marker. Настоящий
launcher выполняет `--help`, `version`, JSON version и read-only JSON doctor без
injection. Отдельный test-only argv driver использует настоящие установленные
file/public/batch/journal components для success, safety/preflight отказов,
zero-backend dry-run, redaction, backend failure и partial batch stop/continue.
Прямой installed API проверяется отдельным процессом с блокировкой CLI SDK до
первого product import: version/read/refusal/failure и следующий успешный вызов.
Полный CLI provenance выполняется отдельно; подменяется только executable argv,
не application, config resolver, read service или parser. Payload/exit/schema
API и CLI сравниваются без нормализации synthetic identical-input результата.
Idempotence повторной redaction и отсутствие marker-bypass проверяются также
через реальные envelope consumers, включая partial batch.
Schema validation выполняет dev-контроллер; `jsonschema` и другие dev packages
не устанавливаются в чистый runtime.

Сам smoke ограничивает команды Windows Jobs либо Linux subreaper/native pidfd;
optional Python pidfd wrappers не требуются, но нужны соответствующие native
Linux APIs. Timeout/неподтверждённый cleanup — failure, не GREEN. Окружение
синтетическое, без Mail.ru credentials, пользовательского config или live tests;
загрузка нужных package dependencies не является cloud-проверкой. Команды запуска
даны в [package smoke test](../README.md#package-smoke-test).
Локальные runtime результаты не являются remote CI run или ordinary-Windows proof.

Installer `setup` имеет отдельные deterministic offline controls для HTTPS policy,
pins/hash-before-execution, unsafe/corrupt archive, activation/cleanup/concurrency,
explicit precedence и network-free dry-run/read-only commands. Обычный pytest/CI
не скачивает rclone. Отдельная real installed проверка использует официальный
pinned rclone: default HTTPS setup на каждой ОС; `--archive`/другие Python cells
используют verified official archive cache с теми же pins без повторной загрузки.
Setup не обещает сохранение скачанного ZIP; архивный GREEN не заменяет default
HTTPS proof. Managed discovery и local-file round-trip выполняются в собственном
изолированном alias root. Это не fake-backed proof, но и не доступ
к Mail.ru. Windows/Linux Python 3.12/3.13 проверены локально; elevated Windows не
становится ordinary-logon qualification. Package содержит только pins/resource,
не executable; реальная зависимость устанавливается явным шагом агента.

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
