# ADR 0005. Live probes before private API

> Статус: accepted  
> Дата: 2026-07-04  
> Проект: `hermes-mailcloud`


## Контекст

Некоторые функции Mail.ru Cloud официально доступны в веб-интерфейсе, но не имеют публичного документированного API. Например:

- закрытие публичной ссылки;
- прямой download URL;
- срок действия ссылки;
- пароль на публичную папку;
- список всех публичных ссылок.

Исторические reverse-engineered клиенты показывают возможные endpoint-и, но их нельзя считать стабильным контрактом.

## Решение

Не писать production private API код до live-probe.

Сначала каждая capability должна пройти отдельный probe-скрипт:

```text
scripts/probes/03_unlink_probe.py
scripts/probes/04_public_url_probe.py
scripts/probes/05_private_api_probe.py
```

Только после успешного probe можно добавлять production command/backend.

## Capability states

Каждая спорная функция должна иметь статус:

| Статус | Значение |
|---|---|
| `unknown` | не проверялась |
| `probe_planned` | есть план проверки |
| `probe_passed` | проверено live |
| `probe_failed` | live-проверка не прошла |
| `implemented` | есть production-команда |
| `unsupported` | не поддерживается текущим backend-ом |

## Обоснование

Private API может измениться. Если сразу писать красивый production-код, можно потратить много времени на функцию, которая не работает на конкретном аккаунте или тарифе.

Probe-first подход дешевле:

```text
small script -> live result -> documented decision -> production code
```

## Последствия

Плюсы:

- меньше лишнего кода;
- меньше догадок;
- понятная матрица возможностей;
- проще объяснить ограничения v0.1.

Минусы:

- разработка идёт медленнее;
- часть функций останется experimental;
- нужны live credentials для полной проверки.

## Required probe output

Каждый probe должен возвращать JSON:

```json
{
  "ok": true,
  "probe": "publish",
  "capability": "public_link_create",
  "result": {
    "supported": true,
    "public_url": "https://cloud.mail.ru/public/..."
  },
  "cleanup": {
    "remote_file_removed": true
  }
}
```

## Revisit criteria

Если private API станет официально документированным или `rclone` закроет нужную функцию, этот ADR можно обновить.
