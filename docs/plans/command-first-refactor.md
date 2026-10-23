---
id: hmc-command-first-refactor
title: "Hermes MailCloud — план выделения независимого Application API"
kind: plan
status: proposed
created: "2026-10-23"
updated: "2026-10-23"
areas: [architecture, application-api, cli, safety, testing]
summary: "Синхронный прикладной API поверх существующих сервисов с сохранением CLI, защит и поставки; конечные вертикальные срезы и критерии приёмки."
code_ref: "3f2f6af386a8b028552ec22f9b16965c51852710"
---

# Результат, область и статус

**Это предлагаемый исполнимый план, не описание уже реализованного API.** База
утверждений о реализации — исходники и тесты указанной редакции; новые foundations
задают направление, но не подтверждают runtime. Принятие плана не означает
выполнение проверок, разрешение публикации или изменение рабочих данных.

Потребность: как пользователь CLI и разработчик следующего адаптера, хочу вызывать
одни и те же операции приложения без Typer, терминала и запуска нашего CLI как
подпроцесса. Для одинакового намерения должны совпадать результат, отказ, правила
конфигурации и допустимые эффекты. CLI продолжает обслуживать существующих агентов.

Основной сценарий: выбрать конфигурацию → вызвать операцию напрямую либо через
CLI → пройти общий допуск → получить результат существующего сервиса и typed error
при отказе. Например, download возвращает результат только после принятого
локального файла; конфликт `never` сохраняет прежние байты. Публикация вне
разрешённого корня отклоняется независимо от оболочки и не создаёт ссылку.

В область входят все поставляемые команды: `version`, `setup`, `doctor`, `ls`,
`stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, `batch`.
Дополнительный Python-вход batch принимает уже декодированный JSON-документ.
Локальный вызывающий код действует с полномочиями текущего процесса: `yes` выражает
подтверждённое намерение, но не аутентифицирует человека или агента. Будущий удалённый
адаптер потребует отдельного доверенного контекста и проверки доступа; добавление
этого API само по себе не разрешает публиковать его в сети.
GUI и MCP сейчас не создаются. Не добавляются `auth`, `unlink`, `resolve`, `sync`,
новый backend, daemon, IPC, фоновые задачи, progress API, Undo, миграция journal,
телеметрия, автоматический setup или новые зависимости в runtime.

Работа начинается в отдельной implementation-ветке после принятия плана и до
редактирования кода. Существующая документационная дельта сохраняется.
Полномочия ролей и независимая приёмка — по [рабочему циклу](../agent-workflow.md).
Этот план не предоставляет права на stage, commit, push, tag или release.

## 1. Реальная основа и недостающая граница

| Ответственность сейчас | Проверенный владелец | Что сохраняем / чего недостаёт |
|---|---|---|
| Парсер, перестановка global options, JSON help/usage, stdout/stderr/exit | [cli.py](../../src/hermes_mailcloud/cli.py): `_GlobalOptionsGroup`, `main`, `_normalize_global_options`, `_emit` | Это действительно обязанности адаптера |
| Сборка config + runner + сервиса, runtime defaults и envelope | Там же: `_run_rclone_command` (455–490), `_run_doctor_command` (493–538), `_run_batch_command` (541–586), `_effective_*` | Переносим в независимый application owner, а не оборачиваем вызов CLI |
| TOML/env/override, безопасные profile fields, discovery executable | [config.py](../../src/hermes_mailcloud/config.py): `resolve_config`, `ResolvedConfig`, `CliConfigOverrides` | Рабочий механизм; нужен нейтральный тип overrides и единый способ его использования |
| Файловые операции | [commands/](../../src/hermes_mailcloud/commands/): `ReadCommands`, `MkdirCommand`, `TransferCommands`, `MoveCopyCommands`, `RemoveCommand` | Уже не зависят от Typer. Не переписываем argv, локальный commit download и защиту rm |
| Публикация, journal preflight и ошибка после эффекта | [commands/public.py](../../src/hermes_mailcloud/commands/public.py): `PublicCommands`, `_record_after_backend` | Уже полноценный сервис, не логика внутри CLI |
| Нормализация и safety | [core/paths.py](../../src/hermes_mailcloud/core/paths.py), [core/policy.py](../../src/hermes_mailcloud/core/policy.py): `validate_operation` | Оставляем один набор предметных правил; аннотации существующих DTO не являются runtime-проверкой всех входов |
| Batch parsing, полная предварительная проверка и ordered execution | [batch/__init__.py](../../src/hermes_mailcloud/batch/__init__.py): `parse_batch_document`, `BatchCommands.run` | Сохраняем этот сценарий и его mapping; не исполняем строки CLI для каждого item |
| Диагностика и bounded live probes | [doctor/__init__.py](../../src/hermes_mailcloud/doctor/__init__.py): `DoctorCommands`; [probes/core.py](../../src/hermes_mailcloud/probes/core.py) | Readiness и cleanup уже реализованы; admission `live + yes` сейчас принадлежит только CLI |
| Typed errors, envelope, sanitization | [core/errors.py](../../src/hermes_mailcloud/core/errors.py), [core/result.py](../../src/hermes_mailcloud/core/result.py), [output.py](../../src/hermes_mailcloud/output.py) | Переиспользуем. `output.py` — чистая обработка данных, а не terminal sink |
| Реальные процессы и платформенные ресурсы | [rclone/runner.py](../../src/hermes_mailcloud/rclone/runner.py), `rclone/_windows_process.py`, `_platform/` | Сохраняем literal argv, bounded capture, native cleanup и private storage |
| Явная установка rclone | [rclone/install.py](../../src/hermes_mailcloud/rclone/install.py): `prepare_rclone` | Самостоятельный рабочий механизм с pins; application лишь вызывает его явно |
| Проверка поставки | [scripts/smoke_installed.py](../../scripts/smoke_installed.py), [installed_fake_driver.py](../../tests/helpers/installed_fake_driver.py) | Реальный launcher и отдельно fake-backed installed путь; после переноса надо изменить точку injection и проверки provenance |

Таким образом, gap — не отсутствие command services, а отсутствие **поддерживаемого
внешнего Python API, общей сборки, admission и результата вызова**. Просто перенести
функции Typer в другой каталог или объявить `commands/` публичным SDK недостаточно.

Текущие тесты уже проверяют существенные инварианты:
[CLI files](../../tests/commands/test_cli_file_commands.py) — профильные read retries
и однократную запись; [transfer](../../tests/commands/test_transfer.py) — temp commit,
сохранение target и конкурентного победителя; [public](../../tests/commands/test_public.py)
и [batch](../../tests/batch/test_batch.py) — journal preflight, post-backend failure,
zero-call dry-run и partial stop/continue; [doctor](../../tests/doctor/test_doctor.py) —
readiness, разные capability states и остановку при недоказанном cleanup.
Они остаются проверками своих владельцев, а новые тесты доказывают соединение API.

Историческая [архитектура](../01-architecture.md) не является фактом наличия
Pydantic, private API или перечисленных в ней модулей. Зависимости принадлежат
[pyproject.toml](../../pyproject.toml) и [uv.lock](../../uv.lock), а машинный CLI-контракт —
[02-command-contract](../02-command-contract.md) и [schemas](../../schemas/).

## 2. Решение: профиль A и его ограничения

Выбран **A — синхронный прикладной сервис**. Операция завершается ответом в пределах
вызова. Даже долгий transfer пока не имеет адресуемого Job после ответа, восстановления
выполнения после restart или управления от другого клиента. Batch — последовательность
с частичными результатами, не workflow и не транзакция. Наличие сохраняемого journal
не превращает приложение в профиль D.

- B потребуется при отдельной жизни работы, позднем получении результата или отмене
  по идентификатору. Таких требований сейчас нет.
- C потребуется для общей живой изменяемой сессии/workspace, а не просто общего
  исходного кода. Сейчас авторитетные файлы находятся в облаке и локальной FS.
- D потребуется для восстановления зависимых этапов через сбои и ожидания.
  Текущая программа не обещает такого восстановления.

API работает headless в процессе вызывающей стороны. Attached-режима нет. Отдельные
процессы не разделяют память и не получают взаимную отмену. Они используют существующие
файловые механизмы согласования journal/setup и фактические гарантии backend.
Не обещаем atomic batch, exactly-once, distributed locking, откат после timeout,
power-loss durability или отсутствие будущей эволюции API.

Основание выбора: [pf-command-first](../../tools/project-foundation/skills/pf-command-first/SKILL.md),
[профили и матрица](../../tools/project-foundation/references/architecture/command-first/03_Command_First_Architecture_Variants.md),
[CLI-first delivery](../../tools/project-foundation/skills/pf-command-first/references/cli-first-delivery.md).

## 3. Целевые зависимости, владельцы состояния и эффектов

```text
cli.py: Typer/Click, presentation, process exit
    ↓
application/: публичные методы, admission, composition, effective options, envelope
    ↓
commands/ + batch/ + doctor/: существующие прикладные сценарии
    ↓
core/paths + core/policy + config + journal + rclone/parser/runner/install + probes
    ↓
внешний rclone / filesystem / явно разрешённый HTTP
```

Это карта ответственности, а не требование линейной цепочки imports. Composition
root вправе знать конкретную инфраструктуру. `core`, сервисы и инфраструктура не
импортируют `application` или `cli`; application не импортирует CLI и его SDK.
`core.result → output` остаётся допустимым: sanitizer/JSON formatter не печатает.
В существующем probe-модуле есть собственный argparse entrypoint; application
использует только функции probes, не вызывает его `main` и не маршрутизирует через argv.

Предлагаемые новые файлы:

| Путь | Ответственность |
|---|---|
| `src/hermes_mailcloud/application/__init__.py` | Небольшой явный export поддерживаемой поверхности |
| `application/contracts.py` | `CallOptions`, `Overwrite`, узкие типы DI; без второй JSON-schema |
| `application/validation.py` | Runtime-типы входов и admission doctor; не копия path/public/overwrite policy |
| `application/composition.py` | Default config loader и backend factory с явным environment |
| `application/service.py` | `MailCloudApplication`, effective options, вызов существующего сценария, safe envelope |

Все сокращённые `application/...` пути в плане относятся к `src/hermes_mailcloud/`.
Не требуется базовый Command, bus, registry, Service Locator или DI framework.

| Ресурс/состояние | Владелец и срок жизни |
|---|---|
| Вход вызова и эффективная конфигурация | Application; один вызов. В batch одна конфигурация на весь пакет |
| Environment | Копия у экземпляра application; не меняет `os.environ`, не сериализуется и не логируется |
| Cloud objects | Mail.ru через существующий rclone; локального authoritative кеша не добавляем |
| Download temp и принятие destination | `TransferCommands` и `_commit_download`; temp принадлежит только этому вызову |
| Capability journal | `LinkJournal` и native storage; stable sidecar lock и read–modify–replace сохраняются |
| Managed rclone generation/activation | Installer и его private lock; без auto-update и cloud configuration |
| Процесс, pipes, handles | `RcloneRunner` и native process implementation; приложение не создаёт свой второй supervisor |
| Live test roots и cleanup | Doctor/probe harness; только сгенерированные same-run `/TEST/hermes-mailcloud-*` |
| Ответ | Новый DTO/его data mappings передаются вызывающему; не ссылка на изменяемое состояние application |
| Формат/канал вывода | Только CLI; будущий адаптер будет отдельным consumer |

Экземпляр не хранит «последний ответ», открытый journal, активный runner или кеш config.
Последовательные вызовы разрешены. Одновременные вызовы с изменяющимися внешними файлами
не получают новых транзакционных гарантий. Изменение config между вызовами перечитывается;
изменение environment требует нового экземпляра либо нового CLI-процесса.

## 4. Публичный Python-контракт

### 4.1. Канон и DTO

Канон нового in-process API — сигнатуры и runtime validation в `application/`.
Семантика описывается этим планом, затем принятой текущей архитектурой. Не заводим
OpenAPI, Pydantic-модели или параллельный реестр команд. Входы небольших операций —
явные аргументы методов; общие параметры — один frozen dataclass. Результат —
существующий `ResultEnvelope`, ошибки — существующие `ErrorKind`/`ErrorPayload`.
Operation-specific поля результата сохраняются в Mapping по действующим сервисам;
не объявляем их полностью статически типизированным новым SDK.

`config.py` получает нейтральное имя `ConfigOverrides` с прежними полями
`profile: str | None`, `remote: str | None`, `config_path: Path | None`, все defaults
равны `None`. Оставить `CliConfigOverrides = ConfigOverrides` как совместимый alias,
а `resolve_config` сохранить callable по прежней сигнатуре. Это переименование
понятия, не новый способ загрузки настроек.

Предлагаемый контракт типов:

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from hermes_mailcloud.commands.backend import RcloneBackend
from hermes_mailcloud.config import ConfigOverrides, ResolvedConfig
from hermes_mailcloud.core.result import ResultEnvelope
from hermes_mailcloud.doctor import DiagnosticBackend
from hermes_mailcloud.probes.core import HttpOpener

Overwrite = Literal["never", "always", "if-newer"]

@dataclass(frozen=True, slots=True)
class CallOptions:
    config: ConfigOverrides = field(default_factory=ConfigOverrides)
    trace_id: str | None = None
    dry_run: bool = False
    yes: bool = False
    timeout_seconds: int | None = None
    retries: int | None = None

class Backend(RcloneBackend, DiagnosticBackend, Protocol):
    pass

class ConfigLoader(Protocol):
    def __call__(self, overrides: ConfigOverrides, *,
                 environment: Mapping[str, str]) -> ResolvedConfig: ...

class BackendFactory(Protocol):
    def __call__(self, config: ResolvedConfig, *,
                 environment: Mapping[str, str]) -> Backend: ...
```

Аннотации и frozen dataclass сами не проверяют значения. Проверку выполняет метод
application **до использования полей и эффектов**, поэтому `yes="false"`,
`dry_run=1`, `retries=True`, `timeout_seconds=float("nan")` не обходят admission.
Некорректное значение аргумента операции возвращает `invalid_arguments`/2.
Неправильная Python-арность или неизвестное keyword остаются обычным `TypeError`
до входа в метод; конструктор DI не является транспортным API для недоверенного JSON.

### 4.2. Исполнимые сигнатуры целевой поверхности

Ниже — объявления будущего API, а не заглушки, которые надо поставить в продукт.
Публиковать только реально реализованные методы соответствующего среза.

```python
class MailCloudApplication:
    def __init__(self, *, environment: Mapping[str, str] | None = None,
                 config_loader: ConfigLoader | None = None,
                 backend_factory: BackendFactory | None = None,
                 http_opener: HttpOpener | None = None) -> None: ...

    def version(self, *, options: CallOptions | None = None) -> ResultEnvelope: ...
    def setup(self, *, archive: Path | None = None,
              options: CallOptions | None = None) -> ResultEnvelope: ...
    def doctor(self, *, live: bool = False,
               options: CallOptions | None = None) -> ResultEnvelope: ...
    def ls(self, remote_path: str, *, recursive: bool = False,
           files_only: bool = False, dirs_only: bool = False,
           options: CallOptions | None = None) -> ResultEnvelope: ...
    def stat(self, remote_path: str, *,
             options: CallOptions | None = None) -> ResultEnvelope: ...
    def mkdir(self, remote_path: str, *,
              options: CallOptions | None = None) -> ResultEnvelope: ...
    def upload(self, local_path: str, remote_path: str, *,
               overwrite: Overwrite | None = None,
               options: CallOptions | None = None) -> ResultEnvelope: ...
    def download(self, remote_path: str, local_path: str, *,
                 overwrite: Overwrite | None = None,
                 options: CallOptions | None = None) -> ResultEnvelope: ...
    def mv(self, source_path: str, target_path: str, *,
           overwrite: Overwrite | None = None,
           options: CallOptions | None = None) -> ResultEnvelope: ...
    def cp(self, source_path: str, target_path: str, *,
           overwrite: Overwrite | None = None,
           options: CallOptions | None = None) -> ResultEnvelope: ...
    def rm(self, remote_path: str, *, recursive: bool = False,
           options: CallOptions | None = None) -> ResultEnvelope: ...
    def publish(self, local_path: str, remote_path: str, *,
                overwrite: Overwrite | None = None,
                options: CallOptions | None = None) -> ResultEnvelope: ...
    def link(self, remote_path: str, *,
             options: CallOptions | None = None) -> ResultEnvelope: ...
    def batch(self, document: object, *,
              options: CallOptions | None = None) -> ResultEnvelope: ...
    def batch_file(self, path: Path, *,
                   options: CallOptions | None = None) -> ResultEnvelope: ...
```

`None` в `options` означает новый набор defaults, а не отключение policy. В `overwrite`
и runtime overrides `None` означает «не задано»; ноль retries — явный нулевой бюджет.
Boolean принимается именно как boolean, timeout — положительный int, retries —
неотрицательный int, без bool и без неявного приведения строк/float. Строковые пути
не превращаются в shell-команды. File-path аргументы `archive`, `batch_file.path`
принимают `Path`; CLI уже преобразует их. Remote/local operation paths остаются
строками, как у действующих сервисов. Смысл путей проверяют существующие owners.

`batch(document)` принимает только JSON-shaped документ и всегда пропускает его
через `parse_batch_document`. Публичного входа «исполнить доверенный BatchPlan без
проверки» нет. `batch_file` использует существующий file parser и тот же внутренний
путь исполнения, не повторяет загрузку конфигурации для каждого item.

### 4.3. Конфигурация и DI

Конструктор только сохраняет зависимости и копию заданной среды; при `None` берётся
копия текущей process environment. Он не читает config/journal, не ищет/исполняет
rclone, не устанавливает зависимость и не печатает. Точка сборки создаёт настоящий
`RcloneRunner(config.rclone_path, environment=...)`; config resolver и installer
получают ту же среду. Не допускается ситуация «config из injected env, backend
из неявного другого `os.environ`».

Загрузку оставить ленивой, на вызов. `version` и help не читают config. Неверный
batch-документ отклоняется до config. Неподтверждённый live doctor — тоже до config.
Для обычной валидной file-команды сохраняется порядок: resolve config → effective
options → существующий сервис → envelope. Создание runner не равно запуску процесса;
контракт dry-run запрещает backend calls и мутации, а не простое создание объекта.
Для setup не нужен даже неиспользуемый file runner: вызывается `prepare_rclone`.

Precedence сохраняется: явный override → HMC env → profile → defaults. Для executable:
`HMC_RCLONE_PATH` → profile `rclone_path` → внешний PATH → verified managed generation.
Ошибочный explicit override не обходится fallback. `RCLONE_CONFIG` остаётся отдельным
backend locator, не application TOML и не объектом credentials в API.

Injection — доверенный seam хоста/тестов, не вход для агента. Нельзя обещать sandbox
произвольному коду, который заменил loader/backend. В обычных integration tests
loader настоящий, TOML синтетический; заменяем только внешний backend/HTTP/источник
установочного архива. Не подменяем application или policy «правильным ответом».

Важно: существующие `Path.home()`/`expanduser()` могут пользоваться process home;
переданный `environment` не является полной файловой sandbox. Не расширять этот
рефакторинг до изменения правил home expansion. Для изоляции нужны явные абсолютные
пути и синтетическая process environment **до импорта**, как описано в разделе 9.

### 4.4. Результаты, ошибки и безопасная граница

Все выполненные вызовы возвращают `ResultEnvelope`; application не вызывает
`typer.Exit`, `sys.exit`, `print`, prompt или logging sink. Ожидаемый `MailCloudError`
превращается в failure без изменения kind/code. Для неожиданного `Exception` на
границе вызова — `unknown_error`/1 с фиксированным безопасным сообщением, без
`str(exc)`, args, traceback или cause; сообщение не обещает отсутствия эффекта.
`KeyboardInterrupt`, `SystemExit` и другие `BaseException` не перехватываются как
успех и не становятся новым API отмены. Общий безопасный unknown-error factory
разместить у существующего owner-а `core/errors.py`, не в CLI.

В batch неожиданная ошибка отдельного выполняемого item превращается в такой же
безопасный item error внутри `BatchCommands.run`, чтобы сохранить уже полученные
items и stop/continue. Нельзя потерять историю выполненного пакета из-за общего
catch только вокруг всего application-вызова. Ошибка preflight остаётся обычной
top-level failure до backend.

Finalizer application возвращает новую безопасную проекцию данных: использует
существующий `sanitize_value` для result, message/details, warnings и metadata,
сохраняет typed `ErrorKind` и shape envelope. Прямой consumer не должен получать raw
capability URL/diagnostics, которые были бы скрыты лишь вызовом `to_json()`.
JSON adapter по-прежнему использует `ResultEnvelope.to_json`, без второго serializer.
Нельзя заменить sanitization на `str()` при ошибке фильтрации.

Поле `operation` использует имя поставляемой команды; оба Python-входа batch возвращают
`operation="batch"`, а не имя вспомогательного метода. Сохраняются `result` XOR `error`,
пропуск отсутствующих optional metadata, существующие warnings и все пары kind/exit.
При partial batch: `ok=false`, top-level `result`,
`status=partial_failure`, exit 11, **без top-level error**. `total` — число попыток,
а не исходная длина плана после остановки. `doctor` с отрицательными readiness checks
может вернуть успешный диагностический отчёт; это не утверждение готовности облака.

## 5. Admission и mapping всех операций

### Общий порядок

1. Проверить тип `CallOptions`, вложенных overrides и operation arguments; не читать
   произвольные атрибуты/значения до проверки. Невалидные scalar types не доходят до FS.
2. Специальный ранний gate doctor и структурный parsing batch — до config.
3. Разрешить конфигурацию и effective timeout/read/write retries один раз.
4. Вызвать существующий сервис, не копируя нормализацию, public-root, deny patterns,
   overwrite и protected-rm правила в façade или адаптер.
5. Сформировать safe typed envelope. CLI только выводит его и применяет `exit_code`.

Для валидно типизированных запросов сохранить существующий приоритет предметных
отказов. Например, public path/dangerous filename проверяются до confirmation
в `validate_operation`; не заменять это ранним общим `if not yes` в CLI.

| Метод / CLI | Реальный owner и результат/эффект | Admission, defaults и dry-run |
|---|---|---|
| `version` | `__version__`, result.version | Без config/backend; JSON profile — выбранное имя/default без чтения файла, remote не добавляется; human печатает версию |
| `setup` | `prepare_rclone`; installed/already_available/dry_run | Только явный вызов. Передать explicit, archive, timeout, environment; без `yes`, cloud config и автообновления; dry-run без скачивания/process/managed writes |
| `doctor(live=False)` | `DoctorCommands.read_only`; checks/capabilities/warnings | version → listremotes при наличии remote → независимые lsd/about; нет ссылок/мутаций/installer |
| `doctor(live=True)` | `DoctorCommands.live`; probes после readiness, cleanup/readback | Только явные live и yes; при отсутствии yes отказ до config. Dry-run/live — явный отказ по разделу 7. Public API не позволяет передать свой test root |
| `ls` | `ReadCommands.ls`; normalized remote_path/items | recursive/files_only/dirs_only boolean; files+dirs запрещены; safe read retries |
| `stat` | `ReadCommands.stat`; валидированные metadata | `lsjson --stat --hash`; directory empty-root metadata и optional hashes сохраняются |
| `mkdir` | `MkdirCommand.run`; created или план | Нет новых parents/exist_ok CLI flags; один write, dry-run без backend |
| `upload` | `TransferCommands.upload`; published=false | Реальный local source; overwrite explicit/profile; только copyto, без link |
| `download` | `TransferCommands.download`; bytes/updated | Temp sibling → commit; never сохраняет существующий/конкурентный target, if-newer сравнивает наблюдаемые timestamps; dry-run без temp |
| `mv`, `cp` | `MoveCopyCommands.move/copy`; source/target/overwrite | Два нормализованных разных пути; moveto/copyto однократно |
| `rm` | `RemoveCommand.run`; recursive/deleted | Реальный вызов требует yes; `/`, `/TEST`, `/Hermes` и configured service roots защищены; deletefile либо purge; dry-run не означает право на реальное удаление |
| `publish` | `PublicCommands.publish`; upload → link → private journal → fingerprint | Нормализованный потомок фиксированного `/Hermes/public`, safe filenames, source, yes, journal preflight; dry-run не требует journal и не записывает его |
| `link` | `PublicCommands.link`; link → journal → fingerprint | Те же public path/name/journal guards; standalone yes не требуется, но операция считается write; HTTP probe не добавляется |
| `batch`, `batch_file` | `BatchCommands.run`; completed либо ordered partial | Общий preflight всех items; любой write требует outer yes, dry-run весь пакет zero-backend, details per-item ошибки остаются ограниченными |

`--dry-run` на standalone `ls`/`stat` и read-only doctor сейчас не делает из чтения
план: это read-only вызовы. Сохраняем это различие и не обещаем zero-backend для
всех global dry-run сочетаний. Zero-backend обязателен для поддерживаемых write
планов, setup и **всего batch**, включая read items.

### Retries, timeout и незавершённые эффекты

- Timeout по умолчанию 60 секунд из config, override — положительный int. У runner
  это бюджет одного запуска с его cleanup, не deadline всего publish/batch/doctor.
  Installer сохраняет собственный общий deadline, ограниченный 90 секундами.
- `ls`/`stat`: explicit retries либо profile retries; повторы только transient
  network/timeout. Сохраняем существующее различие исходной ошибки и retry_exhausted.
- Read-only вызовы doctor используют его существующий цикл и диагностический
  отчёт; не преобразуем failed check в новую top-level ошибку. Live doctor использует
  read retries для readiness/readback, но `_ProbeBackend` не повторяет writes.
- Восьми file/public writes передаётся explicit retries либо **0**, не profile retries.
  Явное положительное значение отклоняется как invalid_arguments даже для dry-run.
  В write-batch explicit positive retries отклоняется до выполнения; read-only batch
  применяет бюджет чтения. `setup` не получает новый retry-loop; принятый global
  retries не превращается в повтор установки.
- Нет автоматического повтора целого publish или batch. Ошибка после copyto, link,
  journal replacement или timeout может следовать уже состоявшемуся эффекту.
  Существующее сообщение `_record_after_backend` и отсутствие unlink rollback
  сохраняются. Journal preflight не гарантирует позднюю запись.
- Cleanup не расширяется до чужих файлов. Download cleanup сейчас best-effort;
  не объявлять его абсолютной гарантией или транзакцией с cloud. Платформенные
  storage/process алгоритмы не переписываются ради новой границы.

### Batch mapping без второго приложения

Оставить `BatchCommands` существующим compound use case под application. Его mapping
к тем же command services является адаптацией frozen batch JSON, а не вторым набором
policy. Не заставлять его рекурсивно вызывать публичный façade с повторным config,
созданием runner и envelope для каждого шага.

| Batch op/поля | Вызов существующего сервиса |
|---|---|
| ls: remote_path, recursive | `ReadCommands.ls` |
| stat: remote_path | `ReadCommands.stat` |
| mkdir: remote_path, parents, exist_ok | `MkdirCommand.run`; omitted/true допустимы, false отклоняется в preflight |
| upload/download: local_path, remote_path, overwrite | Соответствующий `TransferCommands` метод |
| mv/cp: src_remote_path, dst_remote_path | `MoveCopyCommands.move/copy` с преобразованием имён |
| rm: remote_path, recursive | `RemoveCommand.run` с outer yes |
| publish: local_path, remote_path, overwrite | `PublicCommands.publish` с outer yes |
| link: remote_path | `PublicCommands.link`; наличие этого item делает batch пишущим |

Схема batch не тождественна всем standalone flags: нет files_only/dirs_only,
per-item overwrite для mv/cp, setup/doctor/version, рекурсивного batch или per-item
yes/retries. Эти поля не добавлять. Defaults overwrite в batch — plan default,
при отсутствии `never`, **не profile default_overwrite**. Для standalone — explicit
либо profile default. Mapping и тесты обязаны сохранять это осознанное различие.

Реальный batch: outer policy → при public items journal preflight → planning каждого
item → последовательное выполнение. До первого backend вызова ошибка любого
preflight item останавливает весь пакет; подготовка journal при этом уже могла
создать private directory/lock. Не обещать полное отсутствие локальных эффектов
у real preflight. Dry-run никогда не выполняет journal prepare. Planned items не
являются замороженной snapshot FS: upload не может ссылаться на ещё не созданный
предыдущим шагом локальный файл; эту семантику не менять.

## 6. Замороженный CLI, схемы и реальные каналы

Сохранить `hermes-mailcloud = hermes_mailcloud.cli:app`, имена и аргументы команд,
interspersed global options, `--`, JSON help, typed usage error, `--pretty`, Unicode
и literal metacharacters. Help и parser errors — ответственность CLI, а не методы
application. Не генерировать help новым registry.

`CliRuntimeOptions` заменить/сузить до presentation options и `CallOptions` либо
собирать `CallOptions` из parser values. В адаптере после миграции не остаются
`resolve_config`, `RcloneRunner`, `prepare_rclone`, `*Commands`, `_effective_*`,
confirmation gates или batch execution. Разрешены только input translation,
специфика help/usage, rendering и process exit. `quiet`, `debug`, `no-color` не
получают нового поведения только потому, что флаги уже существуют.

Нормативные [result-envelope](../../schemas/result-envelope.schema.json),
[doctor-report](../../schemas/doctor-report.schema.json) и
[batch-plan](../../schemas/batch-plan.schema.json) сохраняются без расширения.
Новые Python-типы не требуют поставлять jsonschema в runtime. Schema validation
остаётся у dev/reviewer, как в installed smoke. Пакет и lock не требуют смены версий
или зависимостей; Pydantic, PyYAML, mypy и новый import-linter не добавляются.

Диагностические каналы по [политике наблюдаемости](../foundation/observability-policy.md):

- JSON stdout — один безопасный envelope, не поток start/tick/result событий.
- Human ошибки — stderr; human success — stdout; partial batch сохраняет exit 11.
  Не переписывать human presentation одновременно с архитектурой.
- Application возвращает warnings/typed facts и ничего не выводит. Существующий
  sanitizer применяется до передачи результата и повторно безопасно при serialization.
- Backend stdout/stderr остаются внутренними transient данными runner/parsers, не
  копируются в details, логи или handoff. Допустимые attempts/timeout units и нули
  не теряются при redaction соседних secrets.
- Raw public capability находится только в локальном owner-private journal.
  Journal — операционное состояние, не лог. Его size/locking/durability правила
  не заменяются observability framework.

Новый постоянный logger/sink, audit stream, tracing framework, export или analytics
не нужен. `--debug` не даёт доступа к содержимому. Существующий trace_id коррелирует
ответ; не обещаем его наличие в journal, где текущий `JournalRecord` его не записывает.

## 7. Найденные расхождения и конкретные решения

Это source-level наблюдения для проверки перед исправлением, не результаты
выполненных regression tests. Они не требуют пересмотра архитектуры.

1. **HMC_PROFILE скрывается CLI-default.** `cli.main` задаёт profile=`"default"`,
   затем всегда передаёт его resolver-у; сам `resolve_config` и
   `test_environment_selects_a_profile_and_cli_profile_wins_over_it` реализуют env
   fallback. Рекомендация: в parser сохранить различие omitted/explicit default
   (`None` либо ParameterSource), а эффективное имя выбирать в application/config.
   Явный `--profile default` по-прежнему сильнее env. Help продолжает объяснять default.
   Это узкое исправление до документированного precedence, а не скрытая совместимость
   с прежним дефектом. Версия без config использует тот же выбор имени из override/env/default.
2. **Live doctor игнорирует dry-run.** `_run_doctor_command` проверяет live/yes,
   но после этого вызывает `live()` без учёта dry_run. Рекомендация: типы → для live
   без yes прежний confirmation_required/9 → для live+yes+dry_run invalid_arguments/2
   до config/backend. Не создавать фиктивный live plan и не добавлять поля в строгую
   doctor schema. Обычный read-only doctor не меняется. Это минимальный безопасный
   отказ ранее неоднозначного сочетания, который должен быть явно описан и проверен.
3. **Batch runtime расходится с JSON-schema в двух структурных случаях.**
   `defaults: null` проходит `_parse_defaults(None)`, хотя schema допускает только
   object; `version: 1.0` удовлетворяет JSON Schema integer/const 1, но `_is_integer`
   принимает только Python int. Рекомендация: отличить отсутствие defaults от null
   (null → invalid_arguments); версию принимать как конечное целочисленное JSON-число
   ровно 1, никогда bool/строку. Схему не ослаблять. В file parser также переводить
   невалидный UTF-8 в безопасный invalid_arguments, не выпускать raw decoding exception.
   Проверить эти случаи настоящим parser и schema validator вместе.
4. **Нет противоречия, требующего расширить public root ради live-теста.**
   Production publish/link фиксированы на `/Hermes/public`, а проектные мутации
   разрешены только под `/TEST`. Поэтому прямой production-public путь проверяется
   offline с fake внешним краем и настоящим journal. Разрешённые live probes работают
   отдельным существующим путём только под `/TEST`; они не доказывают production API
   parity и не дают права на test-only escape hatch.
5. **Imported Python tooling попадает под `ruff check .`.** `[tool.ruff].src`
   задаёт import roots, не исключение обхода. Добавить
   `extend-exclude = ["tools/project-foundation"]` в project Ruff config, сохранив
   исходные default excludes. Не форматировать и не чинить vendored checker ради
   application Ruff. Методический checker проверяется отдельно при работе над пакетом;
   его PyYAML не переносится в приложение. Это настройка области lint, не отмена
   проверок `src`, `tests` или `scripts`.

Пункты 1–3 являются явно предлагаемыми узкими поведенческими коррекциями при принятии
этого плана. Перед каждым зафиксировать воспроизведение на synthetic данных, затем
исправить соответствующий owner и добавить regression; не расширять их в общий audit.
Остальная migration сохраняет действующую семантику. При новом конфликте с frozen
контрактом остановить только затронутую часть и вернуться к архитектурному решению.

## 8. Конечные вертикальные срезы

Один кодер реализует срез, замораживает точные bytes и передаёт независимому reviewer.
Reviewer проверяет реальное соединение, отвечает за затронутые docs/instructions и возвращает
вердикт координатору. Следующий срез не запускается самим worker-ом. Ниже пути —
конечная область соответствующего назначения, не разрешение редактировать соседние
платформенные механизмы. Один файл не редактируется двумя ролями одновременно.

### S1 — Независимая граница и настоящий read-путь

**Результат:** `version`, `ls`, `stat` доступны напрямую и через тонкие CLI handlers;
config/defaults/errors работают без Typer. Это первый законченный consumer API,
а не пакет неиспользуемых абстракций. Исправляется HMC_PROFILE из раздела 7.

Кодер владеет:

- пятью новыми `src/hermes_mailcloud/application/{__init__,contracts,validation,composition,service}.py`;
- `src/hermes_mailcloud/config.py`, `src/hermes_mailcloud/core/errors.py`,
  `src/hermes_mailcloud/cli.py` — только общий seam и migrated read/version handlers;
- новыми `tests/application/test_contract.py`, `test_configuration.py`, `test_read_api.py`
  и `tests/helpers/application.py` для минимальной synthetic test mechanics;
- `tests/core/test_config_and_output.py`, `tests/test_cli_json.py`;
- `tests/helpers/cli_fake.py`, `tests/helpers/installed_fake_driver.py`,
  `tests/packaging/test_installed_smoke.py`, `scripts/smoke_installed.py` — seam/provenance
  и прямой installed read API, без изменения process supervisor smoke;
- `pyproject.toml` — только Ruff vendor exclusion;
- `.github/workflows/ci.yml` — включение `tests/application` ровно в один offline pack.

Порядок: воспроизведение env-profile дефекта → contract/validation/composition →
version/read API → CLI → перенастройка source/installed fake injection и provenance →
focused tests → applicable gates. Во время перехода старые write/system handlers
остаются на прежнем пути; test-only drivers явно inject оба backend seams, не
подменяя сервисы. Runtime legacy switch и fallback «если API не сработал, вызвать
старый CLI» запрещены.

Проверка: прямой импорт/вызов при заблокированных Typer/Click/Rich; zero config/backend
для version; real config precedence, явный default, env-only profile, missing remote,
invalid option types; настоящий read service/parser с fake runner; directory stat,
read retries и safe failures; CLI JSON/exit parity; установленный wheel/read API вне
checkout. Unit spies допустимы для доказательства отсутствия эффекта, но не вместо
успешного соединённого пути.

Reviewer синхронизирует только действующую часть `docs/01-architecture.md`,
`docs/02-command-contract.md`, `docs/06-testing-strategy.md`,
`docs/08-configuration-and-secrets.md`, `docs/11-local-installation.md`,
`docs/README.md`: API пока ограничен reads/version;
план не переименовывается в «полностью реализовано».

### S2 — Все file/public writes через ту же границу

Зависимость: принятый S1. **Результат:** mkdir/upload/download/mv/cp/rm/publish/link
вызываются через application напрямую и из CLI с прежними guards и no-write-retry.

Кодер: `application/service.py`, `contracts.py`, `validation.py`, `cli.py`;
новые `tests/application/test_file_api.py`, `test_public_api.py`;
`tests/helpers/application.py`, `tests/helpers/cli_fake.py`,
`tests/helpers/installed_fake_driver.py`, `scripts/smoke_installed.py`,
`tests/packaging/test_installed_smoke.py`. Существующие command implementations и их
низкоуровневые тесты не меняются, если не обнаружено конкретное препятствие соединению;
переписывать их «для единообразия» не надо.

Проверки: direct+CLI таблица writes, protected rm, dangerous/public roots, строгие
bool inputs, ignored profile read retries vs rejected explicit write retries,
dry-run без backend/temp/journal, download readback и сохранность target,
конкурентный no-clobber, journal preflight до cloud, post-link record failure без
retry/rollback/URL leak. Новый вызов после отказа не наследует состояние предыдущего.
Installed smoke продолжает покрывать настоящие command/journal owners.

Reviewer: актуальные application/CLI/safety разделы `docs/01-architecture.md`,
`docs/02-command-contract.md`, `docs/05-safety-model.md`, `docs/07-agent-integration.md`,
`docs/08-configuration-and-secrets.md`; не редактирует accepted ADR history.

### S3 — Setup, doctor и batch: полный прикладной охват

Зависимость: принятый S2. **Результат:** оставшиеся shipped commands и оба batch-входа
работают без CLI; direct doctor admission и complete batch outcome принадлежат
общему пути. Исправляются doctor dry-run и batch structural drift из раздела 7.

Кодер: `application/service.py`, `contracts.py`, `validation.py`, `composition.py`,
`src/hermes_mailcloud/cli.py`, `src/hermes_mailcloud/batch/__init__.py`,
`src/hermes_mailcloud/doctor/__init__.py` (только устранить утверждение, что доверие
обеспечивает CLI, без переписывания probes); новые
`tests/application/test_system_api.py`, `test_batch_api.py`;
`tests/batch/test_batch.py`, `tests/test_schemas.py`, `tests/test_cli_json.py`,
`tests/packaging/test_rclone_setup.py`, `tests/helpers/application.py`,
`tests/helpers/cli_fake.py`, `tests/helpers/installed_fake_driver.py`,
`tests/packaging/test_installed_smoke.py`, `scripts/smoke_installed.py`.

Сохраняемые service classes — внутренние механизмы, не альтернативный публичный API.
Application не предоставляет конструктор «уже подтверждённого live-вызова» из JSON.
Все supported adapter calls проходят `MailCloudApplication.doctor`; доверенный
внутренний вызов `DoctorCommands.live()` не объявляется sandbox или authentication.

Проверки: source-derived regressions до исправления; actual setup installer с
synthetic archive/pins и заменённой внешней execution/download границей; dry-run и
отсутствие скрытого bootstrap; read-only doctor и live refusal до loader; fake live
workflow с real DoctorCommands/probes, HTTP opener и cleanup readback; оба batch
входа, все discriminated ops, defaults, outer yes, preflight и partial stop/continue,
ошибка неожиданного item без утраты ранних results; schema/parser parity, включая
null, 1.0, bool, неверный UTF-8. Реального HTTP/Mail.ru в offline pack нет.

Reviewer: `docs/01-architecture.md`, `docs/02-command-contract.md`,
`docs/06-testing-strategy.md`, `docs/07-agent-integration.md`,
`docs/foundation/architecture-principles.md`, `docs/foundation/observability-policy.md` —
только подтверждённые владельцы/новые узкие отказы, без новых capabilities.

### S4 — Удаление migration glue и приёмка всей поставки

Зависимость: принятый S3. **Результат:** CLI — единственный тонкий presentation
adapter; нет второго legacy orchestration route; вся матрица независимости и
совместимости проверена на итоговых bytes.

Кодер: `src/hermes_mailcloud/cli.py`, пять файлов `application/` только для остаточного
glue; новый `tests/application/test_boundaries.py`; затронутые
`tests/application/test_contract.py`, `test_configuration.py`, `test_read_api.py`,
`test_file_api.py`, `test_public_api.py`, `test_system_api.py`, `test_batch_api.py`;
`tests/helpers/application.py`, `tests/helpers/cli_fake.py`,
`tests/helpers/installed_fake_driver.py`, `tests/packaging/test_installed_smoke.py`,
`scripts/smoke_installed.py`, `.github/workflows/ci.yml`.

Удалить `_run_rclone_command`, `_run_doctor_command`, `_run_batch_command`,
`_effective_*` и проверенно неиспользуемый `_placeholder`; убрать прямые service
imports из CLI и временную двойную injection из test drivers. Не удалять
совместимый `CliConfigOverrides` alias в этом рефакторинге.

Reviewer отвечает за финальную синхронизацию `README.md`, `docs/README.md`,
`docs/01-architecture.md`, `docs/02-command-contract.md`, `docs/06-testing-strategy.md`,
`docs/07-agent-integration.md`, `docs/08-configuration-and-secrets.md`,
`docs/11-local-installation.md`, трёх `docs/foundation/*.md`,
`instructions/CORE.project.instructions.md`, `instructions/TEST.quality_gates.instructions.md`,
`instructions/LOG.observability.instructions.md` — только затронутые утверждения.
Старые release qualification claims не обновляются без новых соответствующих checks.
При добавлении code-first reference не создавать рядом вторую вручную поддерживаемую
схему API; достаточно текущей архитектуры и ссылки на signatures.

Завершение — критерии следующего раздела и независимый verdict. Никакой из срезов
не делает release и не обновляет operational installation пользователя.

## 9. Проверка, изоляция и поставка

### До первого импорта и collection

Использовать фактический synthetic recipe из [CI](../../.github/workflows/ci.yml)
и [TEST instruction](../../instructions/TEST.quality_gates.instructions.md), а не
надеяться на `tmp_path` после imports. Текущие тестовые модули импортируют CLI на
уровне модуля; в repo нет общего tracked conftest, который гарантировал бы раннюю
изоляцию всего процесса.

Для каждого запуска reviewer создаёт disposable home/config/appdata/localappdata,
TMP/TEMP/TMPDIR, явные synthetic HMC_CONFIG и empty RCLONE_CONFIG, заведомо
несуществующий HMC_RCLONE_PATH и private-journal target. Очищает унаследованные
HMC_PROFILE/HMC_REMOTE/HMC_LIVE/HMC_TEST_ROOT и несвязанные секретные overrides;
fixture явно задаёт необходимые значения. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
`PYTHONDONTWRITEBYTECODE=1`, UTF-8; backend/network fail-closed. Не импортировать
приложение для получения этих paths. Cleanup регистрируется сразу после acquisition,
включая неполный setup. Windows private leaf не предсоздаётся с broad ACL.

Новые API tests используют настоящие config/service/policy/parser/result owners.
Fake rclone допускается в двух формах: узкий recording port для unit/integration
и настоящий runner с Python argv fake для subprocess composition. Fake не реализует
policy/expected overwrite decision второй раз. Сохранность доказывается реальным
readback FS/journal плюс counts, а не одним `called`.

### Обязательная матрица

| Граница | Детерминированные сценарии и достаточное наблюдение |
|---|---|
| Независимость | AST-import test запрещает `cli`, typer/click/rich/GUI/MCP imports в application и нижних owners; CLI не импортирует commands/batch/doctor/runner/installer; отдельный subprocess блокирует CLI SDK imports и выполняет настоящий API read + dry-run/refusal |
| Lazy composition | Constructor/version/help не вызывают loader/factory/process; invalid batch и live без yes не вызывают loader; valid call проходит настоящий loader |
| Config и options | explicit/env/profile/default, env-only profile, explicit default, empty/missing remote, false/0/None, invalid bool/numeric types, timeout; один snapshot env передаётся config/backend/setup |
| Read API vs CLI | Совпадение `to_payload` с parsed stdout и exit, реальные parser shapes, files/dirs conflict, directory stat, optional hashes, transient retries/exhaustion и non-transient refusal |
| Writes | Каждая shipped операция: success, правильный argv и zero-call refusal; profile retries не повторяет write, explicit positive retries отклонён |
| Dry-run | Все file/public writes, setup, read/write batch: backend log пуст, journal/temp/managed directories отсутствуют либо unchanged, meaningful planned result. Live doctor dry-run — явный отказ без effects |
| Download preservation | pre-existing never, timeout с partial temp, concurrent winner, if-newer на реально различимых timestamps; полный readback destination, отсутствие своих temp при успешном cleanup; соседние файлы неизменны |
| Public | public-root traversal/prefix/root-self, dangerous local/remote names, confirmation, missing/unsafe journal; success fingerprint + private record readback; record failure после link сохраняет typed warning meaning, без retry/unlink/raw URL |
| Batch | Обе точки входа и все op mappings; malformed last item отклонён до backend, public journal preflight до первого write; stop/continue, counts/indices/results XOR errors, expected и unexpected item failure; per-item safe error без raw details |
| Doctor | Настоящий read-only порядок; no implicit setup; отрицательные checks не false success readiness; live без yes до config; synthetic `/TEST` workflow, unknown/failed/unsupported и cleanup-before-next-root |
| Setup | Actual installer за внешними test seams; explicit precedence, no download dry-run/help/version/doctor, checked activation/readback; не подменять installer success готовым dict |
| Privacy/каналы | Непустой real producer → application finalizer → envelope → CLI output; нужны safe numbers/zeros/kinds и одновременно отсутствие sentinels credentials/raw URL/provider streams в direct result, stdout и stderr |
| Повторный независимый вызов | После отказа/partial новый вызов того же экземпляра не получает старые flags, results или runner state |
| Схемы | Existing schema/golden suite + paired API/CLI payload validation; batch parser/schema cases. Не добавлять необозначенные JSON examples в docs |
| Поставка | Build wheel/sdist; runtime-only clean install; импорт API из wheel, реальный console launcher, fake-backed installed operations, matching hashes, отсутствие checkout/dev packages |

Архитектурные tests — stdlib AST и subprocess, не новый lint framework. Проверять
absolute и relative imports, а runtime test — транзитивную зависимость и side effects.
Сами `__init__.py` не должны запускать application. Запрет печати относится к
application-вызову и его используемым ветвям, не к существующему отдельному
probe CLI entrypoint. Dependency graph test без исполняемого сценария недостаточен.

### CI и installed harness

`tests/packaging/test_installed_smoke.py::test_ci_test_packs_are_a_disjoint_cover_of_all_test_modules`
проверяет включение каждого test module ровно одним selection path. Поэтому
`tests/application` добавляется в `.github/workflows/ci.yml` одновременно с первым
тестом, не только в конце: отдельный пятый application pack с теми же изоляцией и
timeout; обновить комментарий о количестве packs и testing docs.
Существующие четыре selections остаются disjoint. Не ослаблять контроль покрытия
и не убирать тесты из CI ради лимита; при превышении бюджета разделить selection.

Source driver сейчас подменяет `cli.RcloneRunner`; installed driver дополнительно
проверяет `cli.ReadCommands` и другие service identities. После переноса они должны
подменять **только** `application.composition.create_backend` (предлагаемое имя factory)
и возвращать настоящий runner с test-only executable argv prefix. Default factory
выбирается во время создания application, а не захватывается заранее default-argument
binding, из-за которого injection перестанет работать.

Provenance gate проверяет все новые application modules/hashes и актуальные связи
`application.service → commands/batch/doctor`, включая lazy imports. Сравнения
старых cli service attributes заменяются проверками нового владельца, не удаляются
без эквивалента. Обычный launcher help/version/doctor остаётся **без injection**.
Отдельный installed API режим driver вызывает реальные методы без `cli.app()`,
с проверкой импортов, payload и local readback. До import-independence проверки
этого режима provenance helper не должен предварительно импортировать CLI/его SDK;
проверку полного набора компонентов выполнять отдельным шагом. Нельзя назвать fake-backed driver
проверкой настоящего rclone или Mail.ru.

Проверить, что application файлы входят в wheel; `rclone/releases.json` и native
platform modules остаются package data/code. Wheel не содержит vendor tooling,
тестов, runtime state или rclone binary. Если PFK входит в sdist по существующим
build rules, его LICENSE/UPSTREAM/THIRD_PARTY_NOTICES сохраняются; не добавлять его
runtime requirements. Нельзя чинить проверку отсутствия секретов исключением
нового каталога целиком из artifact safety gate.

### Команды будущей проверки и пределы выводов

После подготовки synthetic environment сначала focused modules своего среза,
затем affected integration/packaging. Например, для S1:

```text
uv run --no-sync --offline python -m pytest -q -ra tests/application tests/core/test_config_and_output.py tests/test_cli_json.py tests/commands/test_cli_file_commands.py tests/packaging/test_installed_smoke.py -m "not live" -p no:cacheprovider
```

Для всего refactor обязательны:

```text
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
git diff --check
```

Full offline selection можно выполнить disjoint CI packs с сохранением полного
охвата. Build/export/clean installed smoke — по текущим командам
[README](../../README.md#package-smoke-test), с новыми disposable output/receipt paths
вне checkout. Offline-флаг внешнего `uv run` не делает сам installer harness offline;
его отдельный `--offline` требует подготовленного dependency cache. Не выполнять
download/install без применимого execution grant следующего поручения.

Итоговую cross-cutting дельту проверяют на Windows/Linux, Python 3.12/3.13 по
существующей matrix. Native platform skip не заменяет другую ОС. Проверка Windows
с повышенными правами не доказывает поддержку обычного пользователя, локальный
прогон не доказывает удалённый CI GREEN. Неизменённые низкоуровневые реализации сохраняют прежние ограничения;
новая поставка получает собственное installed evidence. Не требуются новые реальные
HTTPS/setup или Mail.ru probes только ради переноса composition; если они отдельно
назначены, действуют прежние isolated authorities и `/TEST` boundary.

В приватном handoff каждого исполненного среза указываются exact bytes/base, command,
raw exit, synthetic roots/подмены, skips/NOT_RUN и ограничения. Этот публичный план
не становится журналом прогонов. Новая правка после verdict требует delta-review.

## 10. Переход, возврат и Done

Переход последовательный: read/version → writes/public → system/batch → removal
legacy glue. Каждая мигрированная команда сразу использует настоящий API; старые
пути для неё не оставляются. Internal command services остаются доступными тестам,
но supported consumer surface — `hermes_mailcloud.application`. Не требуется
миграция TOML, journal, managed rclone, schemas или пользовательской установки.

Возврат до приёмки выполняется ограниченной коррекцией в implementation-ветке, по
решению координатора и с сохранением чужих изменений. Не делать reset/stash/checkout
поверх общей dirty работы. При возврате отдельного маршрута тестовый seam и docs
возвращаются согласованно. Отмена code migration не откатывает уже выполненные
cloud/FS эффекты и не разрешает переустановку рабочего CLI или очистку пользовательских
данных. Коммит/публикация остаются отдельным полномочием.

**Вся программа готова к технической приёмке, когда:**

1. Все перечисленные методы реально реализованы; прямой API не импортирует Typer/
   Click/Rich и не требует CLI process, prompt или global mutable app state.
2. Все shipped CLI команды делегируют одному application owner; parser/help/output
   остаются в CLI, orchestration и admission — нет.
3. Frozen schemas/argv/exit/partial/overwrite/retry/public/journal contracts сохранены;
   только узкие дельты раздела 7 явно приняты, реализованы и проверены.
4. Direct API не позволяет обходить guards ложными runtime types; dry-run и refusal
   имеют доказанную границу эффектов, а partial/unknown не объявляются rollback.
5. Новые connected tests вместе с прежними safety/preservation tests включены в CI;
   focused, full offline, lint/format/lock, build и installed evidence относятся к
   итоговым bytes. Непроверенная обязательная platform/cell не называется PASS.
6. Затронутые docs/instructions описывают принятое устройство, не планы; vendor payload
   сохранён, runtime dependencies и рабочие данные не расширены без решения.
7. Независимый reviewer дал verdict по точному кандидату. Без commit grant итог
   остаётся принятым, но не сохранённым коммитом; без push/release grant публикация
   не выполняется и не подразумевается.

После достаточной приёмки остановиться. Возвращаться к Oracle только при доказанном
материальном конфликте контракта/сохранности или невозможности безопасно завершить
один из этих ограниченных срезов, а не для повторного проектирования уже принятого пути.

## Основания

- [Философия проекта](../foundation/project-philosophy.md),
  [архитектурные принципы](../foundation/architecture-principles.md),
  [наблюдаемость](../foundation/observability-policy.md).
- [ADR 0001](../adr/0001-use-rclone-subprocess-first.md),
  [ADR 0002](../adr/0002-json-first-cli-contract.md),
  [ADR 0004](../adr/0004-public-root-safety-policy.md),
  [ADR 0006](../adr/0006-freeze-v0-1-contract-and-test-boundaries.md).
- [Testing strategy](../06-testing-strategy.md),
  [configuration/secrets](../08-configuration-and-secrets.md).
- [PFK 0.3.0](../../tools/project-foundation/README.md),
  [pf-plan](../../tools/project-foundation/skills/pf-plan/SKILL.md),
  [contract evolution](../../tools/project-foundation/references/methods/contract-evolution.md),
  [quality](../../tools/project-foundation/references/quality.md),
  [authoring metadata](../../tools/project-foundation/references/metadata.md).
