# 00. Research Summary — Hermes MailCloud

> [!important]
> **Contract freeze (2026-07-24):** v0.1 requires `doctor`, `ls`, `stat`,
> `mkdir`, `upload`, `download`, `mv`, `cp`, `rm`, `publish`, `link`, and
> `batch`; `unlink` is conditional on a live rclone unlink-plus-invalidation
> proof. `sync`, `resolve`, private API, link expiration/passwords and full
> link audit are post-v0.1; `auth` is not a command. This research record does
> not override the frozen contract or prove current implementation.

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`  
> Назначение: зафиксировать исследование по Mail.ru Cloud, rclone, WebDAV и публичным ссылкам до начала разработки.

---

## 1. Цель документа 🧭

Этот документ фиксирует исходные выводы по реализации агентской CLI-утилиты для Mail.ru Cloud.

Целевой сценарий:

```text
Hermes Agent
  → hermes-mailcloud CLI
  → загрузка / скачивание / структура папок / публикация ссылки
  → JSON-ответ обратно агенту
```

Главная задача проекта — дать агентам безопасный и предсказуемый терминальный инструмент:

```text
upload → publish/link → return JSON → external agent can consume result
```

---

## 2. Что хотим получить 🎯

Первая версия должна закрывать практический цикл:

1. Проверить окружение и доступ к Mail.ru Cloud.
2. Работать с файлами и папками:
   - `ls`
   - `stat`
   - `mkdir`
   - `upload`
   - `download`
   - `mv`
   - `cp`
   - `rm`
3. Загружать файл приватно.
4. Загружать файл и сразу создавать публичную ссылку.
5. Создавать публичную ссылку на уже загруженный объект.
6. Возвращать стабильный JSON для агента.
7. Делать `dry-run` перед опасными операциями.
8. Не публиковать случайно личные данные.

---

## 3. Официальный слой: WebDAV ☁️

Официальная справка Mail описывает доступ к Облаку по WebDAV.

Ключевые факты:

| Факт | Значение для проекта |
|---|---|
| WebDAV поддерживается официально | можно использовать как официальный fallback |
| Endpoint: `https://webdav.cloud.mail.ru` | можно проверять доступ напрямую |
| Для WebDAV нужен пароль внешнего приложения | обычный пароль не подходит |
| С 1 января 2022 обычный пароль для WebDAV закрыт | конфиг должен явно требовать app password |
| На Linux рекомендуется отключить `LOCK` в `davfs2` | native WebDAV-клиент должен учитывать LOCK-риск |

Источник: <https://help.mail.ru/cloud/desktop/webdav/>

### Вывод

WebDAV подходит для базовых файловых операций:

```text
list / download / upload / mkdir / delete / move / copy
```

Но в официальной WebDAV-справке не найдено публичного API для:

```text
create public link
remove public link
list public links
set link expiration
set link password
```

Поэтому WebDAV не должен быть единственным backend-ом v1.

---

## 4. Официальная функция публичных ссылок 🔗

Mail официально поддерживает совместный доступ и публичные ссылки в интерфейсе Облака.

Подтверждённые возможности в пользовательском продукте:

| Возможность | Есть в интерфейсе Mail Cloud |
|---|---:|
| открыть доступ по ссылке к файлу | да |
| открыть доступ по ссылке к папке | да |
| выбрать действия пользователей | да |
| указать срок действия ссылки | да |
| установить пароль на папку | да |
| закрыть доступ | да |

Источник: <https://help.mail.ru/cloud/actions/share/>

Также в справке Mail указан лимит:

```text
В Облаке можно создать максимум 3000 ссылок на файлы.
После достижения лимита старые ссылки постепенно перестают действовать.
Сами файлы остаются в Облаке.
```

Источник: <https://help.mail.ru/cloud/faq/share/>

### Вывод

Функция публичных ссылок существует официально как часть продукта. Но опубликованный официальный программный REST/API-контракт для автоматизации создания ссылок не найден.

---

## 5. Практический слой: rclone 🛠️

Rclone имеет отдельный backend `mailru` для Mail.ru Cloud.

Ключевые факты из документации rclone:

| Факт | Значение |
|---|---|
| Mail.ru Cloud есть как backend `mailru` | можно использовать готовый backend |
| Требуется app password | совпадает с моделью Mail |
| Обычный пароль не подходит | нужно явно описать в `doctor` |
| Файлы и папки можно расшаривать публичными ссылками | закрывает `publish/link` |
| Partial/streaming upload не поддерживаются | размер файла должен быть известен до загрузки |
| Удаление переносит объект в корзину | `rm` не равно “стереть навсегда” |
| Есть `rclone about` для квоты | пригодно для диагностики |

Источник: <https://rclone.org/mailru/>

Команда `rclone link` предназначена для создания, получения или удаления публичной ссылки:

```bash
rclone link remote:path/to/file
rclone link remote:path/to/folder/
rclone link --unlink remote:path/to/folder/
rclone link --expire 1d remote:path/to/file
```

Источник: <https://rclone.org/commands/rclone_link/>

Важное ограничение: `--expire` и `--unlink` зависят от поддержки конкретного backend-а. Если backend не поддерживает `--expire`, ссылка вернётся без срока истечения. Если backend не поддерживает `--unlink`, флаг может быть проигнорирован.

### Вывод

Rclone — лучший backend v1. Он уже закрывает основную практическую задачу:

```text
upload → link → public_url
```

---

## 6. Reverse-engineered слой 🧪

Исторические клиенты и документация reverse-engineering подтверждают существование внутренних API-методов Mail.ru Cloud.

Подтверждённые методы из независимых источников:

```text
POST /api/v2/file/publish
POST /api/v2/file/unpublish
```

Также в актуальном коде rclone Mail.ru backend используется современный путь:

```text
POST /api/m1/file/publish
```

И результат собирается как:

```text
https://cloud.mail.ru/public/ + response_body
```

Референсы:

- rclone source: <https://github.com/rclone/rclone/blob/master/backend/mailru/mailru.go>
- rclone Mail.ru API constants: <https://github.com/rclone/rclone/blob/master/backend/mailru/api/m1.go>
- historical PyMailCloud reference: <https://github.com/mad-gooze/PyMailCloud>
- historical mailru-cloud-api reference: <https://github.com/kireevmp/mailru-cloud-api>

### Вывод

Reverse-engineered слой нужен не для базового файлового цикла, а для функций, которые не закрываются официальным WebDAV и/или rclone:

```text
unlink fallback
public link audit
resolve direct download URL
advanced sharing options
```

В v1 этот слой не должен быть фундаментом.

---

## 7. Лицензионный вывод ⚖️

Предварительная матрица:

| Проект | Лицензия | Использование |
|---|---|---|
| `rclone/rclone` | MIT | можно использовать как внешний backend |
| `scharfff/mailrucloud` | MIT | можно использовать как reference |
| `kireevmp/mailru-cloud-api` | MIT | можно использовать как reference, при копировании сохранять notice |
| `mad-gooze/PyMailCloud` | GPL-2.0 | только research reference, не копировать код |

Решение:

```text
Не форкать rclone в v0.1.
Не копировать код PyMailCloud.
Использовать rclone как внешний CLI-бинарник.
Private-API research is post-v0.1 and never an automatic fallback for a failed probe.
```

---

## 8. Уровень уверенности ✅

| Сценарий | Уверенность | Комментарий |
|---|---:|---|
| `rclone` доступ к Mail.ru Cloud через app password | 98–99% | документировано rclone |
| базовые файловые операции | 99% | rclone + WebDAV |
| upload → public link | 98–99% | rclone docs + source |
| link для существующего файла | 98–99% | `rclone link` |
| unlink | 85–98% | needs live unlink-plus-invalidation proof; otherwise unsupported in v0.1 |
| expire | 70–85% | rclone предупреждает про backend-зависимость |
| password-protected folder link | 60–80% | есть в UI, API требует отдельного исследования |
| direct download URL для агента | 70–90% | отдельная задача `resolve-public` |

---

## 9. Решение для v0.1 🧱

В v0.1 реализуется:

```text
Python CLI
  → rclone subprocess backend
  → JSON-first output
  → safety policy
  → probe scripts
  → doctor command
```

Не реализуется в v0.1:

```text
rclone fork
полный native Mail.ru API client
password-protected public folders
guaranteed link expiration
полный список всех публичных ссылок аккаунта
прямой download URL как обязательный контракт
```

---

## 10. Итог 🏁

Проект можно начинать. Самый безопасный путь:

1. Сначала probe-скрипты.
2. Затем JSON-контракт.
3. Затем CLI-обёртка над rclone.
4. Затем `publish/link`.
5. Затем `unlink/audit/resolve` отдельными волнами.

Главное инженерное правило:

```text
Сначала доказываем возможность маленьким скриптом.
Потом фиксируем контракт.
Потом пишем красивый код.
```
