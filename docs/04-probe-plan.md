# 04. Probe Plan: проверка Mail.ru Cloud перед разработкой 🧪

<!-- hmc-json-example-default: non-contract -->

> [!important]
> **Contract freeze (2026-07-24):** probes establish capability evidence, not
> public CLI scope. v0.1 `unlink` requires a successful rclone unlink and
> public-URL invalidation proof; `sync`, `resolve`, private API, expiration and
> link audit remain post-v0.1. All project-owned live mutations use a unique
> `/TEST/<run-id>/` descendant; public URLs and raw probe output are private
> capability data and never committed or copied into Kanban/chat.

> [!important]
> Этот документ описывает не production-код, а разведочные проверки. Его задача — доказать, что реальные операции Mail.ru Cloud работают на конкретном аккаунте, конкретной машине и конкретной версии `rclone`, прежде чем писать полноценный CLI.

## 1. Назначение документа 🎯

`hermes-mailcloud` должен автоматизировать работу агента Гермес с Облаком Mail.ru: загрузка, скачивание, управление файлами и папками, создание публичных ссылок, а позже — закрытие публичного доступа и аудит ссылок.

До реализации основной архитектуры нужно выполнить набор **probe-скриптов**. Они должны проверить фактическое поведение сервиса и зафиксировать результат в JSON-артефактах.

Главная идея простая:

```text
сначала проверка реального поведения → потом контракт → потом красивый CLI
```

## 2. Что считается доказанным ✅

Core-сценарий считается доказанным, если на live-аккаунте прошла цепочка:

```text
rclone доступен
  → remote Mail.ru настроен
  → можно создать папку
  → можно загрузить файл
  → можно прочитать файл в списке
  → можно скачать файл обратно
  → можно создать публичную ссылку
  → ссылка похожа на https://cloud.mail.ru/public/...
  → тестовые артефакты удалены
```

`unlink` и прямой download URL проверяются отдельно. Они важны, но не блокируют MVP `upload → link → JSON`.

## 3. Внешние зависимости 🔗

| Компонент | Зачем нужен | Статус для v0.1 |
|---|---|---|
| `rclone` | основной рабочий backend | обязателен |
| Mail.ru app password | авторизация в Mail.ru Cloud | обязателен |
| Python 3.12+ | запуск probe-скриптов и будущего CLI | обязателен |
| `curl` или Python HTTP client | проверка публичных ссылок | желательно |
| WebDAV | официальный fallback-слой | исследуется отдельно |

Официальная справка Mail.ru описывает WebDAV-доступ через `https://webdav.cloud.mail.ru` и пароль внешнего приложения. Rclone документирует backend `mailru` и поддержку публичных ссылок.

## 4. Переменные окружения ⚙️

Probe-скрипты не должны хранить секреты в коде. Настройки передаются через env или CLI-флаги.

```bash
export HMC_REMOTE="mailru:"
export HMC_TEST_ROOT="/TEST/hermes-mailcloud-<unique-run-id>"
export HMC_LIVE="1"
```

| Переменная | Пример | Назначение |
|---|---|---|
| `HMC_LIVE` | `1` | разрешает live-проверки |
| `HMC_REMOTE` | `mailru:` | имя rclone remote |
| `HMC_TEST_ROOT` | `/TEST/hermes-mailcloud-<unique-run-id>` | freshly generated test-only descendant |
| `HMC_ARTIFACTS_DIR` | `artifacts/probe-results` | куда писать JSON-отчёты |

> [!warning]
> Пароль внешнего приложения не должен передаваться через аргументы probe-скрипта. Его должен хранить `rclone config` или защищённое окружение.

`01`–`03` refuse to run unless `HMC_LIVE=1`. They accept only a normalized,
generated direct child named `/TEST/hermes-mailcloud-<unique-run-id>` and first
prove that it does not already exist. Every JSON report includes same-run
cleanup accounting; cleanup never expands beyond that root.

## 5. Общий формат JSON-отчёта 📦

Каждый probe должен писать JSON-отчёт. Даже если проверка упала, отчёт должен быть машинно читаемым.

```json
{
  "ok": true,
  "probe": "02_publish_probe",
  "started_at": "2026-07-04T13:00:00+05:00",
  "finished_at": "2026-07-04T13:00:07+05:00",
  "checks": {
    "root_absent": true,
    "mkdir": true,
    "upload": true,
    "link_create": true,
    "public_url_probe": true
  },
  "result": {
    "remote": "mailru:",
    "root": "/TEST/hermes-mailcloud-<unique-run-id>",
    "public_url_fingerprint": "sha256:...",
    "http_accessible": true
  },
  "cleanup": {
    "root": "/TEST/hermes-mailcloud-<unique-run-id>",
    "complete": true
  },
  "artifact": {"requested": false, "written": false},
  "warnings": []
}
```

Ошибка:

```json
{
  "ok": false,
  "probe": "02_publish_probe",
  "error": {
    "kind": "public_link_failed",
    "message": "rclone link did not return a Mail.ru public URL",
    "details": {
      "stdout_tail": "...",
      "stderr_tail": "...",
      "exit_code": 1
    }
  }
}
```

## 6. Probe 00: окружение 🩺

Файл:

```text
scripts/probes/00_env_probe.py
```

Команда:

```bash
uv run python scripts/probes/00_env_probe.py --remote mailru: --json
```

Проверки:

| Проверка | Команда | Успех |
|---|---|---|
| `rclone` найден | `rclone version` | exit code `0` |
| remote существует | `rclone listremotes` | есть `mailru:` |
| есть доступ к облаку | `rclone lsd mailru:` | exit code `0` |
| можно получить about | `rclone about mailru:` | exit code `0` или понятная ошибка backend-а |

Минимальный результат:

```json
{
  "ok": true,
  "probe": "00_env_probe",
  "checks": {
    "rclone_installed": true,
    "remote_exists": true,
    "cloud_access": true
  },
  "result": {
    "rclone_version": "rclone v1.74.3",
    "remote": "mailru:"
  }
}
```

Блокеры:

| Блокер | Что делать |
|---|---|
| `rclone` не найден | установить rclone |
| remote отсутствует | выполнить `rclone config` |
| auth denied | проверить app password |
| root недоступен | проверить аккаунт/сеть/регион |

## 7. Probe 01: базовый файловый цикл 📁

Файл:

```text
scripts/probes/01_file_ops_probe.py
```

Команда:

```bash
HMC_LIVE=1 uv run python scripts/probes/01_file_ops_probe.py --remote mailru: --root /TEST/hermes-mailcloud-<unique-run-id> --json
```

Цепочка:

```text
mkdir root
  → создать локальный tiny-файл
  → upload copyto
  → lsjson
  → download copyto
  → сравнить содержимое
  → moveto
  → deletefile
  → cleanup
```

Команды rclone:

```bash
rclone mkdir mailru:/TEST/hermes-mailcloud-<unique-run-id>
rclone copyto ./hmc-probe.txt mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-probe.txt
rclone lsjson mailru:/TEST/hermes-mailcloud-<unique-run-id>
rclone copyto mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-probe.txt ./hmc-probe-downloaded.txt
rclone moveto mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-probe.txt mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-probe-renamed.txt
rclone deletefile mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-probe-renamed.txt
```

Критерии успеха:

| Операция | Критерий |
|---|---|
| `mkdir` | a proved-absent generated root was created |
| `upload` | файл появился в `lsjson` |
| `download` | локальный файл совпал с исходным |
| `moveto` | старый путь исчез, новый появился |
| `deletefile` | файл исчез из списка |

## 8. Probe 02: создание публичной ссылки 🔗

Файл:

```text
scripts/probes/02_publish_probe.py
```

Команда:

```bash
HMC_LIVE=1 uv run python scripts/probes/02_publish_probe.py --remote mailru: --root /TEST/hermes-mailcloud-<unique-run-id> --json
```

Цепочка:

```text
создать tiny-файл
  → загрузить в cloud
  → rclone link
  → проверить форму ссылки
  → попробовать HEAD/GET
  → записать only public_url_fingerprint in any shared report
  → удалить remote-файл
  → bounded GET must prove the created public capability is invalidated (404/410)
```

Команды:

```bash
rclone copyto ./hmc-public-probe.txt mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-public-probe.txt
rclone link mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-public-probe.txt
```

Проверка формы ссылки:

```text
должна начинаться с https://cloud.mail.ru/public/
```

Возможные результаты проверки публичного URL:

| Результат | Значение |
|---|---|
| HTTP 200/302 | ссылка жива |
| HTML page | ссылка публичная, но не direct-download |
| auth required | возможно ограничение тарифа/аккаунта |
| 404 после создания | publish сломан или ссылка не успела активироваться |

> [!note]
> Public URL не обязан быть прямой download-ссылкой. Для v0.1 достаточно вернуть публичную ссылку Mail.ru. Превращение её в прямой download URL — отдельная задача `resolve`.

## 9. Probe 03: закрытие публичной ссылки 🧹

Файл:

```text
scripts/probes/03_unlink_probe.py
```

Команда:

```bash
HMC_LIVE=1 uv run python scripts/probes/03_unlink_probe.py --remote mailru: --root /TEST/hermes-mailcloud-<unique-run-id> --json
```

Что проверяет:

```text
создать файл
  → создать public link
  → попробовать rclone link --unlink
  → проверить, доступна ли ссылка после unlink
  → зафиксировать поддержку unlink
```

Команда:

```bash
rclone link --unlink mailru:/TEST/hermes-mailcloud-<unique-run-id>/hmc-unlink-probe.txt
```

Возможные итоги:

| Итог | Значение для разработки |
|---|---|
| `unlink_supported=true` | можно использовать rclone для `unlink` |
| `unlink_supported=false` | record unsupported; no v0.1 private-API fallback |
| команда успешна, но ссылка жива | считать `unlink` неподдержанным |
| команда падает | считать неподдержанным |

> [!warning]
> Документация `rclone link` говорит, что `--unlink` зависит от backend-а. Поэтому эту функцию нельзя считать готовой без live-probe.

## 10. Probe 04: проверка публичной ссылки для агента 🌐

Файл:

```text
scripts/probes/04_public_url_probe.py
```

Команда:

```bash
uv run python scripts/probes/04_public_url_probe.py --json < /path/to/owner-private-public-url
```

The raw URL is consumed only from one owner-private stdin descriptor; it is not
accepted as a CLI argument and is never copied to JSON output, an artifact, or a
shell example. Reports contain a `sha256:` fingerprint instead.

Проверки:

Проверки выполняются только для `https://cloud.mail.ru/public/...`: redirect stays
on the same allowlisted host (at most three hops), and GET reads no more than
8 KiB before classifying the response.

| Проверка | Зачем |
|---|---|
| URL shape | убедиться, что это ссылка Mail.ru Cloud |
| HEAD | быстрый HTTP-пробник |
| GET small | понять тип ответа |
| content-type | HTML или файл |
| redirects | куда ведёт ссылка |

Пример ответа:

```json
{
  "ok": true,
  "probe": "04_public_url_probe",
  "result": {
    "public_url_fingerprint": "sha256:example-public-link",
    "http_accessible": true,
    "status_code": 200,
    "content_type": "text/html",
    "direct_download": false,
    "download_mode": "browser_page"
  }
}
```

## 11. Артефакты probe-прогонов 🗂️

Every entry point emits one sanitized JSON object to stdout on success, failure,
`--help`, and argument errors. To retain a local JSON artifact, set `HMC_ARTIFACTS_DIR` or pass
`--artifacts-dir`; artifact writing is optional and the destination is ignored
by Git. Recommended local structure:

```text
artifacts/
  probe-results/
    2026-07-04_130000_00_env_probe.json
    2026-07-04_130010_01_file_ops_probe.json
    2026-07-04_130030_02_publish_probe.json
    2026-07-04_130050_03_unlink_probe.json
```

Правила:

```text
не коммитить секреты
не писать app password
не писать access_token
stdout/stderr обрезать до безопасного tail
raw public URLs are capability data: use a redacted fingerprint in reports
```

## 12. Очистка после проверок 🧽

Каждый live-probe должен пытаться очистить свои файлы. Но очистка не должна скрывать ошибку основной операции.
If a probe created a public capability, file deletion alone is not cleanup:
the probe records only its fingerprint and marks cleanup complete only after a
bounded post-delete request proves invalidation with HTTP `404` or `410`.
An unavailable or still-reachable public capability leaves `complete=false` and
its redacted fingerprint as residual cleanup evidence.

```json
{
  "ok": false,
  "probe": "02_publish_probe",
  "checks": {
    "upload": true,
    "link_create": false,
    "cleanup": true
  }
}
```

Если cleanup не прошёл:

```json
{
  "ok": false,
  "probe": "01_file_ops_probe",
  "error": {
    "kind": "cleanup_failed",
    "message": "Probe file may remain in the current /TEST/hermes-mailcloud-<unique-run-id> root"
  }
}
```

## 13. Gate перед основным CLI 🚦

До реализации основной команды `publish` должны пройти:

```bash
uv run python scripts/probes/00_env_probe.py --remote mailru: --json
HMC_LIVE=1 uv run python scripts/probes/01_file_ops_probe.py --remote mailru: --root /TEST/hermes-mailcloud-<unique-run-id> --json
HMC_LIVE=1 uv run python scripts/probes/02_publish_probe.py --remote mailru: --root /TEST/hermes-mailcloud-<unique-run-id> --json
```

`03_unlink_probe.py` не блокирует `publish`, но блокирует production-реализацию `unlink`.

## 14. Источники и ориентиры 📚

- Mail.ru WebDAV: https://help.mail.ru/cloud/desktop/webdav/
- Mail.ru публичные ссылки: https://help.mail.ru/cloud/actions/share/
- Mail.ru лимит публичных ссылок: https://help.mail.ru/cloud/faq/share/
- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone link command: https://rclone.org/commands/rclone_link/
