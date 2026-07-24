# ADR 0004. Public root safety policy

<!-- hmc-json-example-default: result-envelope -->

> Статус: accepted  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`

> Compatibility note (2026-07-24): ADR 0006 supersedes this ADR's historical
> escape-hatch proposal for v0.1. The current v0.1 contract has no
> `--allow-outside-public-root` flag and fixes `publish`/`link` to normalized
> descendants of `/Hermes/public`.


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
    "message": "Publishing is allowed only inside /Hermes/public.",
    "exit_code": 9
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

## Historical escape-hatch proposal (not v0.1)

This was an early possible design, not a v0.1 feature:

```bash
--allow-outside-public-root
```

ADR 0006 rejects this escape hatch for v0.1, including JSON mode.

## Обоснование

Агентские ошибки обычно происходят не потому, что операция невозможна, а потому что операция слишком легко доступна. Public root создаёт понятную границу:

```text
private work -> /Hermes/private
published artifacts -> /Hermes/public
test-only mutations -> /TEST/<unique-run-id>
```

## Последствия

Плюсы:

- меньше риск случайной публикации;
- проще audit;
- проще объяснить агенту правила;
- проще чистить публичные артефакты.

Минусы:

- пользователь должен соблюдать структуру папок;
- scenarios outside the fixed root are deferred to a later explicit contract;
- нужно тестировать path normalization.

## Required tests

```text
[ ] publish inside /Hermes/public succeeds.
[ ] publish outside /Hermes/public fails.
[ ] link outside /Hermes/public fails by default.
[ ] dangerous filenames fail.
[ ] no v0.1 override flag is accepted.
[ ] normalized paths cannot escape public root.
```
