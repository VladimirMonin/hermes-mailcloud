# 03. Development Plan — Hermes MailCloud

> [!important]
> **Contract freeze (2026-07-24):** the active v0.1 scope is `doctor`, `ls`,
> `stat`, `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`,
> and `batch`; `unlink` is conditional on live rclone unlink plus URL
> invalidation. `sync`, `resolve`, private API, expiration/password links and
> full link audit are post-v0.1. Historical waves below are planning material
> and do not make a command part of the frozen release.

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`  
> Назначение: поэтапный план разработки с волнами, коммитами, проверками и тестами.

---

## 1. Главный принцип разработки 🧭

Разработка идёт не “сразу пишем клиент”, а через доказательства.

```text
Probe scripts → contracts → fake-first implementation → live-gated tests → release
```

Почему так:

```text
Mail.ru Cloud имеет официальный WebDAV-слой, rclone-слой и private API-слой.
Нельзя сразу писать много красивого кода, пока не доказаны операции на реальном аккаунте.
```

Главное правило:

```text
Каждая risky-фича сначала проверяется маленьким script/probe.
Только после этого попадает в основной CLI.
```

---

## 2. Milestone overview 🧱

| Волна | Название | Цель |
|---:|---|---|
| 0 | Docs & repo bootstrap | создать правила игры |
| 1 | Probe scripts | доказать операции на реальном Mail.ru Cloud |
| 2 | Contract core | JSON envelope, ошибки, fake runner |
| 3 | Basic file commands | `ls/stat/mkdir/upload/download/mv/cp/rm` |
| 4 | Publish/link MVP | `publish`, `link`, журнал ссылок |
| 5 | Unlink/audit | закрытие доступа и проверка ссылок |
| 6 | Batch mode | JSON-планы для агентов |
| 7 | Doctor command | одна команда для диагностики |
| 8 | Packaging & release | установка, CI, release v0.1 |

---

## 3. Wave 0 — Docs & repository bootstrap 📚

### Цель

Создать репозиторий и документацию до бизнес-логики.

### Результат

```text
Репозиторий существует.
Структура проекта создана.
Документы 00–03 добавлены.
Лицензионные решения зафиксированы.
```

### Коммиты

| Коммит | Содержание |
|---|---|
| `chore: bootstrap python project` | `pyproject.toml`, `src/`, `tests/` |
| `docs: add initial README` | описание проекта и quick start |
| `docs: add research summary` | `docs/00-research-summary.md` |
| `docs: add architecture draft` | `docs/01-architecture.md` |
| `docs: add command contract draft` | `docs/02-command-contract.md` |
| `docs: add development plan` | `docs/03-development-plan.md` |
| `docs: add third-party licensing notes` | later `THIRD_PARTY_NOTICES.md` |
| `chore: add lint and test tooling` | ruff, pytest, optional mypy/pyright |

### Проверки

```bash
uv sync
uv run python -V
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

### Acceptance criteria

```text
Проект устанавливается локально.
pytest проходит.
ruff проходит.
CLI-заглушка отвечает на --help.
Документы лежат в docs/.
```

---

## 4. Wave 1 — Probe scripts 🧪

### Цель

До основного кода проверить реальные возможности Mail.ru Cloud.

### Почему это важно

Без probe-скриптов нельзя честно утверждать:

```text
rclone remote работает
upload работает
public link создаётся
unlink работает или не работает
public URL пригодна для агента
```

### Скрипты

```text
scripts/probes/00_env_probe.py
scripts/probes/01_file_ops_probe.py
scripts/probes/02_publish_probe.py
scripts/probes/03_unlink_probe.py
scripts/probes/04_public_url_probe.py
```

---

### 4.1 `00_env_probe.py`

#### Вызов

```bash
uv run python scripts/probes/00_env_probe.py --remote mailru: --json
```

#### Проверяет

```text
rclone найден
rclone version
remote существует
rclone about remote:
rclone lsd remote:
```

#### Коммит

```text
feat(probes): add rclone environment probe
```

---

### 4.2 `01_file_ops_probe.py`

#### Вызов

```bash
uv run python scripts/probes/01_file_ops_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
```

#### Проверяет

```text
mkdir
copyto local → remote
lsjson
copyto remote → local
moveto
deletefile
cleanup test files
```

#### Коммит

```text
feat(probes): add file operations probe
```

---

### 4.3 `02_publish_probe.py`

#### Вызов

```bash
uv run python scripts/probes/02_publish_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
```

#### Проверяет

```text
upload tiny file
rclone link remote:path
parse https://cloud.mail.ru/public/...
write probe artifact
```

#### Коммит

```text
feat(probes): add public link probe
```

---

### 4.4 `03_unlink_probe.py`

#### Вызов

```bash
uv run python scripts/probes/03_unlink_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
```

#### Проверяет

```text
rclone link --unlink
public URL after unlink
whether backend really removed link
```

#### Коммит

```text
feat(probes): add unlink capability probe
```

---

### 4.5 `04_public_url_probe.py`

#### Вызов

```bash
uv run python scripts/probes/04_public_url_probe.py --public-url "https://cloud.mail.ru/public/..." --json
```

#### Проверяет

```text
HEAD/GET доступность
content-type
redirect chain
можно ли получить direct download URL
```

#### Коммит

```text
feat(probes): add public URL accessibility probe
```

---

### Wave 1 gate

```bash
uv run python scripts/probes/00_env_probe.py --remote mailru: --json
uv run python scripts/probes/01_file_ops_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
uv run python scripts/probes/02_publish_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
uv run python scripts/probes/03_unlink_probe.py --remote mailru: --root /TEST/<unique-run-id> --json
```

### Acceptance criteria

```text
file ops confirmed
publish confirmed
public URL returned
unlink status known
probe artifacts saved
cleanup completed
```

---

## 5. Wave 2 — Contract core 📦

### Цель

Сделать core-модель без реального Mail.ru и без реального rclone.

### Модули

```text
core/result.py
core/errors.py
core/paths.py
core/policy.py
rclone/runner.py
rclone/parser.py
config.py
output.py
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(core): add result envelope model` | `ok/result/error/warnings` | unit |
| `feat(core): add typed error model` | `error.kind` | unit |
| `feat(core): add path normalization` | remote path rules | unit |
| `feat(core): add safety policy` | public root, dangerous patterns | unit |
| `feat(rclone): add runner interface` | fake subprocess | unit |
| `feat(rclone): add output parsers` | `link`, `lsjson`, errors | golden |
| `feat(cli): add Typer skeleton` | commands placeholder | CLI tests |

### Проверки

```bash
uv run pytest -q -m "not live"
uv run ruff check .
uv run ruff format --check .
```

### Acceptance criteria

```text
Все unit/golden tests проходят.
CLI имеет команды-заглушки.
JSON envelope стабилен.
Ошибки типизированы.
```

---

## 6. Wave 3 — Basic file commands 📁

### Цель

Реализовать базовые файловые операции через rclone.

### Команды

```text
ls
stat
mkdir
upload
download
mv
cp
rm
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(commands): implement ls` | `rclone lsjson` | fake + golden |
| `feat(commands): implement stat` | metadata lookup | fake |
| `feat(commands): implement mkdir` | `rclone mkdir` | fake |
| `feat(commands): implement upload` | `rclone copyto` | fake |
| `feat(commands): implement download` | `rclone copyto` | fake |
| `feat(commands): implement mv and cp` | move/copy | fake |
| `feat(commands): implement safe rm` | `--yes` gate | policy |
| `test(live): add basic file ops tests` | real remote | live |

### Live test command

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live tests/live/test_file_ops.py
```

### Acceptance criteria

```text
upload/download работают live
rm требует --yes
ls возвращает стабильный JSON
ошибки rclone нормализуются
```

---

## 7. Wave 4 — Publish/link MVP 🔗

### Цель

Закрыть главный сценарий Гермеса:

```text
local file → cloud path → public URL → JSON
```

### Команды

```text
publish
link
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(policy): enforce public root for publish` | `/Hermes/public` gate | unit |
| `feat(policy): block dangerous publish patterns` | `.env`, keys, db | unit |
| `feat(commands): implement link via rclone` | `rclone link` | fake + golden |
| `feat(commands): implement publish` | upload + link | fake integration |
| `feat(journal): record public links` | `links.jsonl` | unit |
| `test(live): add publish live test` | real public link | live |
| `docs: update publish/link examples` | command docs | review |

### Live smoke

```bash
hermes-mailcloud publish ./fixtures/hello.txt /Hermes/public/hello.txt --json --yes
hermes-mailcloud link /Hermes/public/hello.txt --json
```

### Acceptance criteria

```text
publish возвращает public_url
public_url начинается с https://cloud.mail.ru/public/
publish запрещён вне /Hermes/public
dangerous files blocked
link journal writes event
```

---

## 8. Wave 5 — Unlink and audit 🧹

### Цель

Научиться закрывать публичный доступ и проверять ссылки.

### Команды

```text
unlink
links list
links audit
```

### План

```text
1. Проверить rclone link --unlink.
2. Если реально работает — использовать rclone.
3. Если нет — зафиксировать `unlink` как unsupported and keep it out of v0.1.
4. Full links audit and any private-API research remain post-v0.1.
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(journal): add links list` | локальный список ссылок | unit |
| `feat(commands): add unlink command skeleton` | пока backend-gated | unit |
| `test(live): add unlink capability test` | real remote | live |
| `feat(commands): add unlink via rclone when supported` | `--unlink` | fake/live |
| `feat(commands): add links audit` | HTTP probe | fake HTTP |
| `docs: document unlink support matrix` | docs | review |

### Historical post-v0.1 private API research

If `rclone --unlink` does not pass its invalidation proof, v0.1 records
`unsupported`; it does not add a fallback. Any later private-API research is a
separate post-v0.1 proposal:

| Коммит | Содержание |
|---|---|
| `feat(private-api): add session spike` | auth/session probe |
| `feat(private-api): add file unpublish probe` | `file/unpublish` |
| `feat(commands): add private-api unlink fallback` | backend `auto` |

### Acceptance criteria

```text
unlink status known
links journal readable
links audit works against public URLs
private API не попадает в core без probe
```

---

## 9. Wave 6 — Batch mode 🤖

### Цель

Дать агенту возможность передавать JSON-план операций.

### Команда

```bash
hermes-mailcloud batch plan.json --json --dry-run
hermes-mailcloud batch plan.json --json --yes
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(batch): add operation plan schema` | pydantic/json schema | unit |
| `feat(batch): add dry-run planner` | no execution | golden |
| `feat(batch): execute mkdir/upload/publish` | fake backend | integration |
| `feat(batch): add partial failure report` | stable errors | unit |
| `test(live): add simple batch live test` | real remote | live |

### Acceptance criteria

```text
batch dry-run ничего не меняет
batch execution работает с mkdir/upload/publish
partial failure returns `result.items` and process exit 11
each `result.items` entry has index/operation/ok and exactly one result or error
```

---

## 10. Wave 7 — Doctor command 🩺

### Цель

Сделать одну команду для диагностики готовности.

### Команда

```bash
hermes-mailcloud doctor --json
```

### Коммиты

| Коммит | Содержание | Тесты |
|---|---|---|
| `feat(doctor): add rclone checks` | installed/version | fake |
| `feat(doctor): add remote checks` | about/lsd | fake |
| `feat(doctor): add file ops checks` | mkdir/upload/download | live |
| `feat(doctor): add publish checks` | public link | live |
| `feat(doctor): add unlink capability report` | supported/unsupported | live |
| `docs: add troubleshooting guide` | help docs | review |

### Acceptance criteria

```text
doctor показывает все ключевые проверки
live doctor cleans only its own `/TEST/<unique-run-id>/` descendants
doctor возвращает warnings вместо скрытых догадок
```

---

## 11. Wave 8 — Packaging and release 🚀

### Цель

Подготовить v0.1 к использованию.

### Коммиты

| Коммит | Содержание |
|---|---|
| `docs: add command reference` | полная справка |
| `docs: add agent integration guide` | как вызывать из Гермеса |
| `docs: add safety model` | правила публикации |
| `build: package as uv tool` | entrypoint |
| `ci: add lint and test workflow` | GitHub Actions |
| `release: prepare v0.1.0` | changelog |

### Проверки

```bash
uv build
uv tool install dist/*.whl
hermes-mailcloud --help
hermes-mailcloud doctor --json
uv run pytest -q
```

### Acceptance criteria

```text
утилита устанавливается
--help работает
doctor работает
publish/link работают live
README содержит quick start
v0.1 release notes готовы
```

---

## 12. Тестовая стратегия 🧪

### Типы тестов

| Тип | Назначение |
|---|---|
| unit | логика без rclone и сети |
| fake integration | CLI + fake rclone runner |
| golden | стабильные JSON-ответы |
| live | реальный Mail.ru Cloud |
| probe | экспериментальные проверки возможностей |

### Команды

```bash
uv run pytest -q
uv run pytest -q -m "not live"
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live
```

### Что обязательно покрыть

```text
publish запрещён вне public_root
dangerous file patterns blocked
rm без --yes падает
rclone write retries are never automatic without an operation-specific idempotency decision
rclone link parser принимает только cloud.mail.ru/public
rclone errors превращаются в stable error.kind
JSON не содержит секреты
batch partial failure стабилен
```

---

## 13. Definition of Done для v0.1 ✅

v0.1 готова, если:

```text
doctor проходит file ops + publish
publish возвращает public_url
link работает для существующего файла
ls/mkdir/upload/download/mv/cp/rm работают
все команды имеют --json
опасные действия требуют --yes
publish ограничен public_root
секреты не попадают в вывод
unit/fake/golden tests зелёные
минимум один live-прогон сохранён как probe artifact
README и command docs актуальны
```

---

## 14. Что не делать до v0.1 ❌

```text
не форкать rclone
не копировать GPL-код
не писать полный Mail.ru private API client
не обещать expire/password links
не обещать direct download URL как часть publish
не делать TUI
не запускать rclone RC server
```

---

## 15. Итог 🏁

Порядок работ:

```text
Wave 0 → Wave 1 → Wave 2 → Wave 3 → Wave 4
```

После Wave 4 уже есть полезный MVP:

```text
upload/download + publish/link + JSON
```

Дальше можно спокойно наращивать:

```text
unlink/audit → batch → doctor → release
```

Главное:

```text
Никакой магии.
Каждая внешняя возможность сначала доказывается probe-скриптом.
```
