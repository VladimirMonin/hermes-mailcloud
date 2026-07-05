# ADR 0002. JSON-first CLI contract

> Статус: accepted  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`


## Контекст

`hermes-mailcloud` проектируется не как обычная пользовательская утилита, а как инструмент для агентов. Агенту нельзя полагаться на красивый текстовый вывод, прогресс-бары, ANSI-цвета и интерактивные вопросы.

Нужен контракт, который можно стабильно парсить:

```text
command -> JSON envelope -> ok/result/error -> exit code
```

## Решение

Все команды должны поддерживать `--json`.

В `--json` режиме:

1. stdout содержит только JSON;
2. интерактивные вопросы запрещены;
3. прогресс-бары запрещены;
4. секреты запрещены в stdout/stderr;
5. ошибки возвращаются в едином формате;
6. exit code соответствует типу ошибки.

## Базовый envelope

Успех:

```json
{
  "ok": true,
  "operation": "publish",
  "trace_id": "optional-trace-id",
  "profile": "default",
  "remote": "mailru:",
  "result": {},
  "warnings": []
}
```

Ошибка:

```json
{
  "ok": false,
  "operation": "publish",
  "trace_id": "optional-trace-id",
  "error": {
    "kind": "unsafe_public_path",
    "message": "Publishing is allowed only inside /Hermes/public.",
    "details": {}
  }
}
```

## Exit codes

| Код | Значение |
|---:|---|
| `0` | успех |
| `1` | неизвестная ошибка |
| `2` | ошибка аргументов/валидации |
| `3` | ошибка конфигурации |
| `4` | `rclone` не найден |
| `5` | remote не настроен |
| `6` | auth/access denied |
| `7` | объект не найден |
| `8` | конфликт имени |
| `9` | запрещённое действие |
| `10` | network/retry exhausted |
| `11` | partial failure |
| `12` | функция backend-ом не поддержана |

## Последствия

Плюсы:

- агенту проще интегрироваться;
- ошибки становятся предсказуемыми;
- batch-режим можно строить поверх тех же структур;
- live-probe и тесты могут проверять JSON-схемы.

Минусы:

- человекочитаемый вывод становится вторичным;
- придётся поддерживать backward compatibility JSON-контракта;
- нельзя менять поля без версии схемы.

## Compatibility policy

После релиза v0.1:

- нельзя удалять существующие поля без major version;
- можно добавлять новые необязательные поля;
- `error.kind` должен быть стабильным;
- JSON-схемы в `schemas/` являются контрактом.

## Human output

Человекочитаемый вывод разрешён только без `--json`.

В будущем можно добавить:

```bash
hermes-mailcloud ls /Hermes --pretty
```

Но агентские сценарии должны использовать:

```bash
hermes-mailcloud ls /Hermes --json
```
