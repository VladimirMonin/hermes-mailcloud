# 08. Configuration and Secrets: конфигурация и секреты ⚙️

<!-- hmc-json-example-default: non-contract -->

> [!important]
> **Frozen v0.1 configuration contract (2026-07-24):** `auth` is not a CLI
> command; read-only `doctor` reports readiness without exposing credentials.
> Live doctor/probes use a generated `/TEST/<run-id>/` descendant, never a
> fixed user-facing cloud root. Public URLs and raw provider output are
> owner-private capability data: local journal storage is allowed, but Git,
> artifacts, logs, Kanban and chat use redaction/fingerprints only.

> [!important]
> `hermes-mailcloud` не должен хранить пароль Mail.ru в своём обычном конфиге. В v0.1 авторизация делегируется `rclone`, а наш конфиг хранит только профили, пути, политики и настройки поведения CLI.

## 1. Общая модель 🧭

```text
Mail.ru app password
  → хранится в rclone config / защищённом хранилище
  → rclone выполняет операции с Mail.ru Cloud
  → hermes-mailcloud вызывает rclone и отдаёт JSON агенту
```

В v0.1:

| Что | Где хранится |
|---|---|
| Mail.ru login/app password | `rclone config` |
| имя remote | config `hermes-mailcloud` |
| public/private roots | config `hermes-mailcloud` |
| links journal path | config `hermes-mailcloud` |
| live test env | переменные окружения |

## 2. Rclone remote 🔐

Создание remote:

```bash
rclone config
```

Рекомендуемый remote name:

```text
mailru
```

В командах он будет выглядеть как:

```text
mailru:
```

Проверка:

```bash
rclone lsd mailru:
rclone about mailru:
```

> [!note]
> Для Mail.ru backend rclone нужен пароль внешнего приложения, а не обычный пароль аккаунта.

## 3. Конфиг hermes-mailcloud 📄

Linux/macOS:

```text
~/.config/hermes-mailcloud/config.toml
```

Windows:

```text
%APPDATA%\hermes-mailcloud\config.toml
```

Пример:

```toml
[profiles.default]
remote = "mailru:"
rclone_path = "rclone"

private_root = "/Hermes/private"
public_root = "/Hermes/public"
temp_root = "/Hermes/.tmp"
# doctor --live receives a fresh /TEST/<unique-run-id>/ test root per run;
# it is not a persistent configurable user-data root.

links_journal = "~/.local/share/hermes-mailcloud/links.jsonl"

# Safety
default_overwrite = "never"
deny_dangerous_publish = true
require_yes_for_destructive = true
probe_public_url_after_publish = true

# Runtime
timeout_seconds = 120
retries = 0  # write operations are never retried automatically in v0.1
```

## 4. Профили 🧩

Профили нужны для разных аккаунтов или разных сценариев.

```toml
[profiles.default]
remote = "mailru:"
public_root = "/Hermes/public"
private_root = "/Hermes/private"

[profiles.work]
remote = "mailru-work:"
public_root = "/Hermes/public"
private_root = "/Hermes/private"

[profiles.test]
remote = "mailru-test:"
public_root = "/Hermes/public"
private_root = "/Hermes/private"
```

Вызов:

```bash
hermes-mailcloud --profile work ls /HermesWork --json
```

## 5. Приоритет настроек ⚖️

Порядок применения:

```text
CLI-флаги
  → env vars
  → profile config
  → defaults
```

Пример:

```bash
hermes-mailcloud --profile work --remote mailru-test: doctor --json
```

`--remote` переопределяет remote из профиля.

## 6. Переменные окружения 🌱

| Переменная | Назначение |
|---|---|
| `HMC_PROFILE` | профиль по умолчанию |
| `HMC_REMOTE` | rclone remote |
| `HMC_CONFIG` | путь к config.toml |
| `HMC_LINKS_JOURNAL` | путь к журналу ссылок |
| `HMC_LIVE` | разрешить live-тесты |
| `HMC_TEST_ROOT` | fresh `/TEST/<unique-run-id>/` root for an explicit live run |
| `HMC_RCLONE_PATH` | путь к бинарнику rclone |

Пример:

```bash
HMC_REMOTE=mailru: hermes-mailcloud doctor --json
```

## 7. Чего нельзя хранить в config.toml 🚫

```text
Mail.ru app password
OAuth access token
CSRF token
cookies
Authorization headers
rclone obscure password
```

Неправильно:

```toml
[profiles.default]
remote = "mailru:"
password = "my-app-password"
```

Правильно:

```toml
[profiles.default]
remote = "mailru:"
```

## 8. Links journal 🧾

Linux/macOS:

```text
~/.local/share/hermes-mailcloud/links.jsonl
```

Windows:

```text
%LOCALAPPDATA%\hermes-mailcloud\links.jsonl
```

Формат:

```json
{"ts":"2026-07-24T13:00:00Z","profile":"default","remote":"mailru:","operation":"publish","remote_path":"/Hermes/public/report.pdf","public_url_fingerprint":"sha256:...","trace_id":"..."}
```

Журнал не является источником истины Mail.ru. Это локальная история операций утилиты.

## 9. Секреты в логах 🕵️

Любой вывод rclone должен проходить sanitization перед попаданием в JSON/log.

Маскируем:

```text
access_token=...
token=...
Password=...
Authorization: Bearer ...
Cookie: ...
```

Пример:

```text
access_token=***
Authorization: Bearer ***
Cookie: ***
```

## 10. Конфиг для разработки 🛠️

`.env.example`:

```bash
HMC_REMOTE=mailru:
HMC_TEST_ROOT=/TEST/<unique-run-id>
HMC_LIVE=0
```

`.env` не коммитить.

`.gitignore`:

```gitignore
.env
.env.*
!.env.example
artifacts/probe-results/*.json
*.log
```

## 11. Конфиг для CI 🤖

Обычный CI не должен иметь Mail.ru credentials.

CI запускает:

```bash
uv run pytest -q -m "not live"
```

Live workflow только вручную:

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live
```

Секреты для live workflow должны храниться в secret storage CI, если такой режим вообще будет использоваться.

## 12. Doctor checks 🩺

`doctor` reports readiness without exposing credential-bearing configuration
details. Its frozen v0.1 JSON result is:

<!-- hmc-json-example: doctor-report -->
```json
{
  "ok": true,
  "operation": "doctor",
  "result": {
    "mode": "read_only",
    "checks": {
      "rclone_installed": true,
      "rclone_version": "1.74.3",
      "remote_configured": true,
      "cloud_access": true
    },
    "capabilities": {
      "file_ops": "unknown",
      "public_link_create": "unknown",
      "public_link_unlink": "unknown"
    }
  }
}
```

Но `doctor` не должен показывать секреты.

## 13. Ротация app password 🔄

Если пароль внешнего приложения скомпрометирован:

```text
1. Отозвать пароль в настройках Mail.ru.
2. Создать новый app password.
3. Обновить rclone config.
4. Запустить read-only `hermes-mailcloud doctor --json`.
5. If explicitly authorized, use a new `/TEST/<unique-run-id>/` descendant for
   any live capability check; do not use existing cloud data.
```

## 14. Acceptance criteria ✅

Конфигурационная модель готова, если:

```text
config.toml не содержит секретов
rclone remote используется как источник credentials
env vars могут переопределить профиль
doctor показывает активный профиль без секретов
links journal создаётся в ожидаемом месте
секреты маскируются в логах и ошибках
```

## 15. Источники и ориентиры 📚

- Mail.ru пароли внешних приложений: https://help.mail.ru/mail/login/mailer/
- Mail.ru WebDAV: https://help.mail.ru/cloud/desktop/webdav/
- Rclone Mail.ru backend: https://rclone.org/mailru/
- Rclone config: https://rclone.org/docs/
