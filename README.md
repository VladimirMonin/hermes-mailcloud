# Hermes MailCloud

> Статус: draft  
> Дата: 2026-07-04  
> Назначение: агентская CLI-утилита для автоматизации Mail.ru Cloud  
> Основной backend v0.1: `rclone` как внешний бинарник

## 1. Что это

`hermes-mailcloud` — это терминальная утилита для автономных агентов, которым нужно работать с Mail.ru Cloud:

- загружать файлы;
- скачивать файлы;
- создавать папки;
- получать список файлов и папок;
- перемещать и переименовывать объекты;
- удалять объекты с явным подтверждением;
- публиковать файл и возвращать публичную ссылку;
- выполнять пакетные операции по JSON-плану;
- отдавать стабильный JSON-ответ для агентских пайплайнов.

Главная цель проекта — не заменить весь веб-интерфейс Облака Mail.ru, а дать агенту безопасный и предсказуемый инструмент:

```text
local artifact -> upload -> optional public link -> JSON result
```

## 2. Главный принцип v0.1

В первой версии проект не форкает `rclone` и не переписывает весь Mail.ru Cloud API.

Решение v0.1:

```text
Hermes Agent
  -> hermes-mailcloud CLI
  -> policy + JSON contract
  -> rclone subprocess
  -> Mail.ru Cloud
```

Причины:

1. `rclone` уже поддерживает Mail.ru Cloud.
2. `rclone` умеет создавать публичные ссылки через команду `rclone link`.
3. У проекта MIT-лицензия.
4. Утилите для агента важнее стабильный контракт, чем собственная реализация всех сетевых деталей.

## 3. Что входит в v0.1

Планируемые команды:

```text
auth       Проверка профиля и окружения
doctor     Диагностика rclone, remote, upload/download/publish
ls         Список файлов и папок
stat       Метаданные объекта
mkdir      Создание папки
upload     Загрузка файла
download   Скачивание файла
mv         Перемещение или переименование
cp         Копирование
rm         Удаление с явным подтверждением
publish    Загрузить файл и создать публичную ссылку
link       Создать или получить публичную ссылку для существующего объекта
unlink     Закрыть публичный доступ, если backend подтверждён live-probe
resolve    Проверить публичную ссылку
batch      Выполнить JSON-план операций
```

## 4. Что не входит в v0.1

В v0.1 не обещаются:

- срок жизни публичной ссылки;
- пароль на публичную папку;
- тонкая настройка прав доступа по ссылке;
- полный список всех публичных ссылок аккаунта;
- прямой download URL вместо web/public URL;
- собственный полный клиент Mail.ru Cloud API;
- форк `rclone`;
- копирование GPL-кода из исторических клиентов.

Эти функции могут появиться после live-probe и отдельного ADR.

## 5. Требования

Минимально:

- Python 3.12+;
- установленный `rclone`;
- настроенный `rclone remote` типа `mailru`;
- пароль внешнего приложения Mail.ru с доступом к Облаку;
- `uv` для разработки, если проект ведётся через `uv`.

Пример ожидаемого remote:

```text
mailru:
```

## 6. Быстрый старт разработки

```bash
uv sync
uv run hermes-mailcloud --help
uv run pytest -q
```

Проверка реального доступа выполняется только явно:

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live
```

## 7. Быстрый старт пользователя

Сначала настраивается `rclone`:

```bash
rclone config
```

Затем проверяется доступ:

```bash
rclone lsd mailru:
```

После этого запускается диагностика:

```bash
hermes-mailcloud doctor --remote mailru: --json
```

## 8. Примеры команд

Загрузить файл приватно:

```bash
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
```

Загрузить и опубликовать:

```bash
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

Получить ссылку на уже загруженный файл:

```bash
hermes-mailcloud link /Hermes/public/report.pdf --json
```

Удалить файл:

```bash
hermes-mailcloud rm /Hermes/private/old.txt --json --yes
```

Выполнить batch-план:

```bash
hermes-mailcloud batch plan.json --json --dry-run
hermes-mailcloud batch plan.json --json --yes
```

## 9. JSON-first контракт

В агентском режиме все команды должны использовать `--json`.

Успех:

```json
{
  "ok": true,
  "operation": "publish",
  "result": {
    "remote_path": "/Hermes/public/report.pdf",
    "public_url": "https://cloud.mail.ru/public/..."
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
    "message": "Publishing is allowed only inside /Hermes/public."
  }
}
```

## 10. Безопасность

Главные правила:

1. `upload` всегда приватный.
2. Публикация выполняется только через `publish` или `link`.
3. Публикация по умолчанию разрешена только внутри `/Hermes/public`.
4. Опасные файлы (`.env`, `.key`, `.pem`, `.db`, `cookies*`, `tokens*`, `secrets*`) не публикуются.
5. `rm`, `sync --delete` и `unlink` требуют `--yes`.
6. Пароли, токены и app password не должны попадать в stdout, stderr, JSON и логи.

## 11. Документация

Основные документы:

```text
docs/
  00-research-summary.md
  01-architecture.md
  02-command-contract.md
  03-development-plan.md
  04-probe-plan.md
  05-safety-model.md
  06-testing-strategy.md
  07-agent-integration.md
  08-configuration-and-secrets.md
  09-known-risks.md
```

ADR:

```text
docs/adr/
  0001-use-rclone-subprocess-first.md
  0002-json-first-cli-contract.md
  0003-do-not-copy-gpl-code.md
  0004-public-root-safety-policy.md
  0005-live-probes-before-private-api.md
```

Схемы:

```text
schemas/
  result-envelope.schema.json
  batch-plan.schema.json
  doctor-report.schema.json
```

## 12. Лицензия

Проект предлагается выпускать под MIT License.

См. `LICENSE` и `THIRD_PARTY_NOTICES.md`.
