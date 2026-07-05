# Third-Party Notices — Hermes MailCloud

> Статус: draft  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`

## 1. Назначение документа

Этот файл фиксирует сторонние проекты, документацию и исследовательские источники, которые учитывались при проектировании `hermes-mailcloud`.

Главный принцип:

> В v0.1 проект использует `rclone` как внешний CLI-бинарник и не включает исходный код сторонних клиентов Mail.ru Cloud внутрь репозитория.

## 2. Runtime / external tools

| Компонент | Роль | Лицензия | Использование в проекте |
|---|---|---|---|
| `rclone/rclone` | Основной backend v0.1 через subprocess | MIT | Внешний бинарник, не vendored-код |

`rclone` может быть установлен отдельно пользователем или средой, где работает агент. Проект `hermes-mailcloud` не обязан распространять бинарник `rclone` вместе с собой.

Если в будущем будет принято решение поставлять `rclone` внутри дистрибутива, нужно отдельно обновить этот документ, добавить upstream license notice и проверить формат распространения.

## 3. Research references

| Проект | Роль | Лицензия | Разрешённое использование |
|---|---|---|---|
| `rclone/rclone` | Живой production-grade reference для Mail.ru Cloud backend и public links | MIT | Можно использовать как внешний backend; код можно изучать; копирование возможно только с сохранением notice |
| `scharfff/mailrucloud` | WebDAV-oriented Python CLI reference | MIT | Можно изучать; при копировании существенных частей сохранить notice |
| `kireevmp/mailru-cloud-api` | Документация reverse-engineered API v2 | MIT | Можно использовать как research/reference; при копировании сохранить notice |
| `mad-gooze/PyMailCloud` | Исторический reverse-engineered Python-клиент | GPL-2.0 | Только research reference; код не копировать |

## 4. GPL policy

`PyMailCloud` распространяется под GPL-2.0. Поэтому для проекта `hermes-mailcloud` принимается правило:

```text
Не копировать код, классы, функции, структуру реализации или существенные фрагменты PyMailCloud.
```

Разрешено:

- читать проект как исторический источник сведений о поведении API;
- фиксировать в research-документах факт существования endpoint-ов;
- писать собственную реализацию clean-room способом;
- ссылаться на проект как на внешний источник.

Запрещено без отдельного юридического/лицензионного решения:

- вставлять GPL-код в репозиторий;
- адаптировать GPL-функции с минимальными изменениями;
- vendor-ить GPL-пакет;
- строить распространяемую производную работу на основе GPL-кода, если проект должен оставаться MIT.

## 5. MIT references policy

Код из MIT-проектов можно использовать только при соблюдении условий лицензии:

1. Сохранить copyright notice.
2. Сохранить permission notice.
3. Указать источник в этом файле.
4. Желательно добавить комментарий в коде рядом с адаптированным фрагментом.

На старте проекта предпочтение отдаётся clean-room реализации и вызову `rclone` через subprocess.

## 6. Official documentation references

Официальные источники Mail.ru:

- WebDAV-доступ к Облаку Mail.ru: `https://help.mail.ru/cloud/desktop/webdav/`
- Публичные ссылки и доступ по ссылке: `https://help.mail.ru/cloud/actions/share/`
- Лимиты и особенности ссылок: `https://help.mail.ru/cloud/faq/share/`
- Пароли внешних приложений: `https://help.mail.ru/mail/login/mailer/`

Документация rclone:

- Mail.ru Cloud backend: `https://rclone.org/mailru/`
- Команда `rclone link`: `https://rclone.org/commands/rclone_link/`
- RC API, если будет рассматриваться в будущих версиях: `https://rclone.org/rc/`

## 7. Current decision

Для v0.1:

```text
Use rclone as external subprocess backend.
Do not fork rclone.
Do not vendor third-party Mail.ru Cloud clients.
Do not copy GPL code.
Keep all reverse-engineered behavior behind probe scripts and ADRs.
```

## 8. When this file must be updated

Обновить этот файл нужно, если проект:

- начнёт распространять `rclone` бинарником;
- скопирует код из MIT-проекта;
- добавит private API implementation;
- добавит WebDAV-native backend на основе стороннего клиента;
- поменяет лицензию проекта;
- решит использовать GPL-зависимость.
