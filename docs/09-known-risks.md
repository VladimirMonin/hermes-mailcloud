# 09. Known Risks: известные риски и ограничения ⚠️

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
| `unlink` не поддержан rclone backend | средняя | среднее | P1 | private API fallback после probe |
| public URL не direct download | высокая | среднее | P1 | отдельная команда `resolve` |
| `--expire` не работает | высокая | низкое/среднее | P2 | не обещать в v0.1 |
| пароль на папку не автоматизируется | средняя | низкое | P3 | отложить |
| лимит 3000 ссылок | средняя | среднее | P2 | links journal + audit |
| случайная публикация личного файла | средняя | критическое | P0 | public root + deny patterns |
| утечка app password в лог | низкая/средняя | критическое | P0 | sanitization + tests |
| rclone не установлен | средняя | среднее | P1 | `doctor` и понятная ошибка |
| remote не настроен | средняя | среднее | P1 | `doctor` и setup docs |

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
v0.1: возвращать public_url
v0.2: добавить resolve public URL
v0.2/v0.3: добавить direct_download_url, если найден стабильный способ
```

### 3.2. Анонимное скачивание может зависеть от условий аккаунта

Официальная справка Mail.ru указывает нюансы скачивания по ссылке без авторизации. Поэтому `resolve` должен проверять фактическое поведение ссылки.

Митигация:

```text
после publish опционально делать HEAD/GET probe
в JSON возвращать download_mode
не обещать direct download без проверки
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
если rclone unsupported — private API file/unpublish
```

Статус:

```text
publish: P1 для v0.1
unlink: P1 для v0.2, либо experimental в v0.1 после live-подтверждения
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

## 8. Риски синхронизации 🔁

`sync` может удалить файлы на стороне назначения, если включён delete-режим.

Для v0.1:

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
| нет rclone | exit code 4 | установить rclone |
| remote не настроен | exit code 5 | `rclone config` |
| auth failed | exit code 6 | проверить app password |
| network timeout | exit code 10 | retry/backoff |
| rate limit | exit code 10 | повторить позже |
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
mkdir
upload
download
mv/cp/rm
publish
link
JSON output
safety policies
fake tests
live publish probe
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
или принято решение делать private API fallback
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
