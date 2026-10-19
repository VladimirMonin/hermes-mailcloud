# 09. Known Risks: известные риски и ограничения ⚠️

> [!important]
> **Frozen v0.1 scope (2026-07-24):** `doctor`, `ls`, `stat`, `mkdir`,
> `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, and `batch` are
> required. `unlink` is conditional on live rclone unlink plus URL invalidation
> evidence. `sync`, `resolve`, private API, expiration/password links and full
> link audit are post-v0.1; `auth` is not a command. Any conflicting text below
> is a risk/history note rather than an implementation promise.

> [!important]
> Этот документ фиксирует риски `hermes-mailcloud`, чтобы разработка не скатилась в “оно вроде работало вчера”. Некоторые функции Mail.ru Cloud официально существуют в интерфейсе, но не имеют публичного документированного API. Это нужно честно учитывать.

## 1. Текущий статус уверенности 🧭

Core-сценарий:

```text
upload file → create public link → return JSON to agent
```

оценивается как реализуемый с высокой уверенностью, потому что:

```text
rclone поддерживает Mail.ru Cloud backend
rclone документирует public links для Mail.ru
rclone link умеет создавать ссылки
в исходниках rclone есть метод PublicLink для Mail.ru
reverse-engineered клиенты подтверждают publish/unpublish endpoints
```

Но остаются зоны риска:

```text
unlink
expire
пароль на публичную папку
direct download URL
поведение для разных тарифов и аккаунтов
изменение private API Mail.ru
```

## 2. Risk matrix 📊

| Риск | Вероятность | Влияние | Приоритет | Митигировать как |
|---|---:|---:|---:|---|
| `rclone link` перестанет работать | низкая/средняя | высокое | P1 | live doctor + fallback research |
| `unlink` не поддержан rclone backend | средняя | среднее | P1 | record unsupported; no v0.1 fallback |
| public URL не direct download | высокая | среднее | P1 | не обещать document-byte download; `resolve` — только post-v0.1 proposal |
| `--expire` не работает | высокая | низкое/среднее | P2 | не обещать в v0.1 |
| пароль на папку не автоматизируется | средняя | низкое | P3 | отложить |
| лимит 3000 ссылок | средняя | среднее | P2 | links journal + audit |
| случайная публикация личного файла | средняя | критическое | P0 | public root + deny patterns |
| утечка app password в лог | низкая/средняя | критическое | P0 | sanitization + tests |
| rclone не установлен | средняя | среднее | P1 | read-only `doctor`, затем явный `setup`; invalid explicit path исправить отдельно |
| remote не настроен | средняя | среднее | P1 | `doctor` и отдельная настройка remote, не dependency `setup` |

## 3. Риски публичных ссылок 🔗

### 3.1. Public URL не равен direct download URL

Ссылка вида:

```text
https://cloud.mail.ru/public/...
```

может вести на страницу Mail.ru Cloud, а не на прямой файл.

Влияние:

```text
агент-получатель может не скачать файл через простой curl/wget
```

Митигация:

```text
v0.1: JSON возвращает public_url_fingerprint; raw URL остаётся в private journal
v0.2 proposal: добавить resolve public URL
v0.2/v0.3: добавить direct_download_url, если найден стабильный способ
```

### 3.2. Анонимное скачивание может зависеть от условий аккаунта

Официальная справка Mail.ru указывает нюансы скачивания по ссылке без авторизации. Поэтому `resolve` должен проверять фактическое поведение ссылки.

Митигация:

```text
v0.1: доступность HTML landing page не доказывает скачивание document bytes
post-v0.1 proposal: direct-download classification и поле download_mode
не обещать direct download без отдельной проверки
```

### 3.3. Лимит публичных ссылок

Mail.ru указывает лимит до 3000 ссылок на файлы. После достижения лимита старые ссылки могут перестать действовать, но файлы остаются.

Митигация:

```text
вести links journal
добавить links audit
добавить links cleanup/unlink позже
```

## 4. Риски `unlink` 🧹

`rclone link --unlink` документирован как общая возможность команды `link`, но поддержка зависит от backend-а.

Риск:

```text
команда может не работать для Mail.ru backend или не закрывать ссылку фактически
```

Митигация:

```text
не считать unlink частью v0.1 MVP
сначала 03_unlink_probe.py
если rclone unsupported — сообщить unsupported; private API fallback запрещён в v0.1
```

Статус:

```text
publish: required v0.1 capability
unlink: absent until a live rclone unlink plus public-URL invalidation proof;
        otherwise explicitly unsupported, with no private-API fallback in v0.1
```

## 5. Риски private API 🧪

Некоторые функции, например `file/unpublish`, подтверждены reverse-engineered клиентами, но не являются официально опубликованным публичным API.

Риски:

```text
endpoint может измениться
требуется CSRF/cookie/token flow
авторизация может отличаться от app password/rclone flow
поведение может отличаться по аккаунтам
```

Митигация:

```text
private API не использовать в ядре v0.1
изолировать в отдельный модуль
добавить feature flag
покрыть live-probe
не копировать GPL-код
```

## 6. Лицензионные риски ⚖️

| Источник | Риск | Решение |
|---|---|---|
| rclone | MIT, низкий риск | использовать как внешний binary |
| kireevmp/mailru-cloud-api | MIT, низкий риск | можно как reference |
| scharfff/mailrucloud | MIT, низкий риск | можно как reference |
| PyMailCloud | GPL-2.0 | не копировать код |

Правило:

```text
GPL-код не копировать в проект.
Историческое поведение можно описывать своими словами в research docs.
```

## 7. Риски удаления файлов 🧨

`rclone deletefile`, `purge`, `sync --delete` могут привести к потере данных.

Митигация:

```text
rm требует --yes
folder rm требует --recursive --yes
sync --delete требует --delete --yes
purge не публиковать как v0.1 command
dry-run для sync обязателен перед выполнением
```

## 8. Post-v0.1 risk: синхронизация 🔁

`sync` может удалить файлы на стороне назначения, если включён delete-режим.

Post-v0.1 proposal:

```text
sync push/pull можно реализовать без delete
sync --delete отложить или сделать только с двойным подтверждением
```

Рекомендуемое поведение:

```bash
hermes-mailcloud sync push ./dir /Hermes/private/dir --json --dry-run
hermes-mailcloud sync push ./dir /Hermes/private/dir --json --yes
```

Для удаления:

```bash
hermes-mailcloud sync push ./dir /Hermes/private/dir --delete --json --yes
```

## 9. Риски путей и имён файлов 📁

Mail.ru/rclone backend может иметь ограничения:

```text
case-insensitive имена
запрещённые символы
особенности Unicode
конфликты имён
```

Митигация:

```text
нормализовать remote paths
тестировать конфликтные имена
иметь overwrite policy: never/always/if-newer
не обещать поддержку любых имён в v0.1
```

## 10. Риски больших файлов 🧱

Rclone документация для Mail.ru backend указывает ограничения по streaming/partial uploads: размер файла должен быть известен заранее.

Митигация:

```text
перед upload проверять локальный файл и размер
не поддерживать stdin streaming в v0.1
для больших файлов показывать понятную ошибку
добавить --max-size policy
```

## 11. Операционные риски 🧰

| Риск | Симптом | Что делать |
|---|---|---|
| нет rclone | exit code 4 | агент запускает `hermes-mailcloud setup`; invalid explicit override не обходится |
| remote не настроен | exit code 5 | отдельный интерактивный `config` выбранного rclone; `setup` не настраивает аккаунт |
| auth failed | exit code 6 | проверить app password |
| network timeout | exit code 14 | retry only explicitly safe read-only work |
| rate limit | exit code 10 | повторять только явно безопасную read-only операцию; ambiguous write не повторять |
| corrupted stdout | parse error | включить `--debug` |

## 12. Риски для агента 🤖

Агент может:

```text
неправильно выбрать remote path
публиковать слишком много файлов
попытаться обойти public root
игнорировать warnings
не обработать partial failure
```

Митигация:

```text
строгий command contract
policy errors
batch dry-run
links journal
trace_id
agent integration guide
```

## 13. Что не обещаем в v0.1 ❌

```text
срок жизни публичной ссылки
пароль на публичную папку
полный список всех ссылок аккаунта
прямой download URL
полный native WebDAV backend
полный private API client
GUI/TUI
интерактивный файловый менеджер
```

## 14. Что обязательно должно быть в v0.1 ✅

```text
doctor
ls
stat
mkdir
upload
download
mv/cp/rm
publish
link
batch
JSON output
safety policies
fake tests
explicit read-only/live doctor split
```

## 15. Decision checkpoints 🚦

Перед началом разработки:

```text
принять docs 00–09
принять licensing policy
принять safety model
```

Перед реализацией `publish`:

```text
02_publish_probe.py прошёл на live-аккаунте
```

Перед реализацией `unlink`:

```text
03_unlink_probe.py доказал поддержку rclone unlink
or records `unsupported`; private API is not a v0.1 fallback
```

Перед релизом v0.1:

```text
doctor проходит на целевой машине
golden JSON tests зелёные
live publish test зелёный
секреты не попадают в вывод
```

## 16. Источники и ориентиры 📚

- Mail.ru WebDAV: https://help.mail.ru/cloud/desktop/webdav/
- Mail.ru публичные ссылки: https://help.mail.ru/cloud/actions/share/
- Mail.ru лимит ссылок: https://help.mail.ru/cloud/faq/share/
- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
- Rclone GitHub: https://github.com/rclone/rclone
