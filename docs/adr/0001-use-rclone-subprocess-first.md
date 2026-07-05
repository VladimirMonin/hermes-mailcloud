# ADR 0001. Use rclone subprocess first

> Статус: accepted  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`


## Контекст

`hermes-mailcloud` должен дать агенту полный цикл работы с Mail.ru Cloud: загрузка, скачивание, управление папками и создание публичных ссылок.

Есть три возможных пути:

1. писать собственный Mail.ru Cloud client;
2. форкать `rclone`;
3. вызывать `rclone` как внешний бинарник.

Собственный клиент даст больше контроля, но потребует больше reverse-engineering, live-проверок и поддержки. Форк `rclone` даст доступ к уже реализованному backend-у, но создаст постоянную обязанность поддерживать fork, мерджить upstream и собирать бинарники.

## Решение

В v0.1 использовать `rclone` через subprocess.

```text
hermes-mailcloud CLI
  -> rclone runner
  -> rclone binary
  -> Mail.ru Cloud backend
```

Не форкать `rclone` на старте.

## Обоснование

- `rclone` уже поддерживает Mail.ru Cloud.
- `rclone` умеет создавать публичные ссылки через `rclone link`.
- У `rclone` MIT-лицензия.
- Subprocess-интеграция проще, безопаснее и быстрее для MVP.
- Агенту нужен стабильный JSON-контракт, а не собственная низкоуровневая реализация API.

## Последствия

Плюсы:

- быстрый MVP;
- меньше reverse-engineering;
- меньше сетевого кода;
- проще live-probe;
- проще обновлять backend через обновление `rclone`.

Минусы:

- пользовательская среда должна иметь установленный `rclone`;
- часть ошибок придёт из stdout/stderr внешнего процесса;
- придётся парсить вывод `rclone`;
- не все функции `rclone link` гарантированно поддерживаются Mail.ru backend-ом.

## Implementation notes

В коде нужен отдельный слой:

```text
rclone/runner.py
rclone/parser.py
rclone/errors.py
```

`runner.py` отвечает за запуск процесса, timeout, retries и сбор stdout/stderr.  
`parser.py` превращает вывод `rclone` в стабильные структуры.  
`errors.py` мапит ошибки в `error.kind`.

## Revisit criteria

Решение нужно пересмотреть, если:

- subprocess окажется слишком медленным;
- понадобится много операций подряд;
- `rclone` не сможет закрыть критичные сценарии;
- потребуется встроенный portable binary;
- потребуется тонкий контроль над private API.

Возможное развитие:

```text
v0.1: subprocess
v0.2: private API fallback
v0.3: optional rclone RC
v0.4: native backend only if justified
```
