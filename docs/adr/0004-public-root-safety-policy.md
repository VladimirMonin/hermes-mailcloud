# ADR 0004. Public root safety policy

> Статус: accepted  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`


## Контекст

Одна из главных функций `hermes-mailcloud` — загрузить файл в Mail.ru Cloud и создать публичную ссылку для дальнейшей передачи агентам или другим системам.

Это опасная операция: агент может случайно опубликовать личные данные, токены, базы, cookies или рабочие файлы.

Нужно ограничить публикацию так, чтобы действие было явным и контролируемым.

## Решение

В v0.1 публичная публикация разрешена только внутри public root:

```text
/Hermes/public
```

Команды `publish` и `link` по умолчанию должны отклонять пути вне этой зоны.

Пример запрещённого действия:

```bash
hermes-mailcloud publish ./report.pdf /Personal/report.pdf --json
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

## Дополнительные правила

Публикация запрещена для опасных файлов:

```text
.env
*.env
*.key
*.pem
*.p12
*.pfx
*.db
*.sqlite
cookies*
tokens*
secrets*
credentials*
```

Опасные действия требуют `--yes`:

```text
rm
unlink
sync --delete
batch with destructive operations
```

## Escape hatch

Для ручных сценариев можно добавить флаг:

```bash
--allow-outside-public-root
```

Но в `--json` режиме этот флаг должен быть явным. Никаких интерактивных подтверждений.

## Обоснование

Агентские ошибки обычно происходят не потому, что операция невозможна, а потому что операция слишком легко доступна. Public root создаёт понятную границу:

```text
private work -> /Hermes/private
published artifacts -> /Hermes/public
temporary checks -> /Hermes/.doctor
```

## Последствия

Плюсы:

- меньше риск случайной публикации;
- проще audit;
- проще объяснить агенту правила;
- проще чистить публичные артефакты.

Минусы:

- пользователь должен соблюдать структуру папок;
- часть сценариев потребует явного override;
- нужно тестировать path normalization.

## Required tests

```text
[ ] publish inside /Hermes/public succeeds.
[ ] publish outside /Hermes/public fails.
[ ] link outside /Hermes/public fails by default.
[ ] dangerous filenames fail.
[ ] override works only with explicit flag.
[ ] normalized paths cannot escape public root.
```
