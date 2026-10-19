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

Сначала агент устанавливает Python-пакет и явно выполняет `hermes-mailcloud setup`;
это готовит зависимость, но не создаёт remote. Облачная настройка — отдельный
интерактивный `config` у уже выбранного rclone (external или managed), с вводом
секретов непосредственно в rclone, не в CLI argv/чат. Агент не требует искать
executable или менять PATH; порядок установки и выбора бинарника описан в
[local installation](11-local-installation.md#3-configure-mailru-separately).

Рекомендуемый remote name:

```text
mailru
```

В командах он будет выглядеть как:

```text
mailru:
```

После настройки remote read-only проверка выполняется обычным CLI, который
сам находит подготовленную копию:

```bash
hermes-mailcloud --remote mailru: --json doctor
```

> [!note]
> Для Mail.ru backend rclone нужен пароль внешнего приложения, а не обычный пароль аккаунта.

## 3. Конфиг hermes-mailcloud 📄

The implemented default follows `XDG_CONFIG_HOME` on every supported platform:

```text
${XDG_CONFIG_HOME:-~/.config}/hermes-mailcloud/config.toml
```

Set `HMC_CONFIG` or pass `--config` to use a different path. The current code
does not substitute a separate `%APPDATA%` default.

Пример:

```toml
[profiles.default]
remote = "mailru:"
# Omit rclone_path to allow external-PATH -> managed fallback after setup.
# A configured rclone_path is always an explicit executable override.

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

The implemented configuration core accepts only these profile fields. It rejects
secret-bearing or unsupported fields (including `password`), requires the
frozen `/Hermes/public` value, and does not permit a profile to disable the
confirmation or dangerous-name policies.

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

Для executable порядок: explicit `HMC_RCLONE_PATH` → explicit profile
`rclone_path` → внешний `rclone` в supplied PATH → проверенная managed copy.
Даже значение `rclone_path = "rclone"` считается explicit: если оно ошибочно,
setup/обычные команды не заменяют его managed fallback. Для managed режима
оставьте ключ незаданным; существующие overrides не переписываются автоматически.
Read-only lookup ничего не скачивает и не создаёт. Явный `setup` хранит binary
в per-user data, не в config/site-packages; пути и ограничения —
[Prepare rclone](11-local-installation.md#prepare-rclone).

## 6. Переменные окружения 🌱

| Переменная | Назначение |
|---|---|
| `HMC_PROFILE` | профиль по умолчанию |
| `HMC_REMOTE` | rclone remote |
| `HMC_CONFIG` | путь к config.toml |
| `HMC_LINKS_JOURNAL` | путь к журналу ссылок |
| `HMC_LIVE` | разрешить live-тесты |
| `HMC_TEST_ROOT` | fresh `/TEST/hermes-mailcloud-<unique-run-id>` root for an explicit live run |
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

`links_journal` has no built-in default path: `publish` and `link` require an
explicit profile value or `HMC_LINKS_JOURNAL`. A POSIX-style path example is:

```text
~/.local/share/hermes-mailcloud/links.jsonl
```

Choose an owner-private path appropriate to the host platform; do not put the
journal in the repository, a shared artifact directory, or CI output.

### Windows journal boundary

The native Windows journal backend is limited to Windows 11 x64 and a local
fixed NTFS volume. Use an explicit absolute canonical path under a writable
local parent, with a dedicated private leaf directory. Leave a new leaf absent
so the CLI can create it privately; do not pre-create it with inherited broad
permissions. An existing directory is accepted only if its security descriptor
already satisfies the supported form; the CLI does not repair someone else's ACL.

The directory, journal, stable sidecar lock and temporary files use a protected
DACL with an explicit full-access owner ACE. Only the current owner, SYSTEM and
BUILTIN\\Administrators may be granted access. Broad/NULL/inherited or unsupported
complex ACLs are rejected. This isolates capability data from other ordinary
users, not from processes of the same user, administrators, SYSTEM or holders of
backup/restore privileges. Windows `chmod` is not an ACL privacy check.

FAT/network storage, reparse points (including junctions/symlinks in the path),
8.3 aliases, trailing dots/spaces, alternate data streams and device-name/path
forms are unsupported and fail closed. Redirected profiles may therefore need
another suitable local path; do not bypass the refusal by weakening permissions.
Configuration defaults remain XDG/`~/.config`, not an automatic APPDATA migration.

Journal updates hold one stable sidecar lock across read–modify–replace, with
bounded contention waiting. Do not delete the sidecar while commands may use it.
For installation and durability limits, see
[Windows storage limits](11-local-installation.md#windows-storage-limits).

### Failure after a public operation

`publish`, `link` and a batch containing them preflight journal storage before
backend effects. This cannot guarantee that a later write will succeed: the
backend may already have created the link when local recording fails. The CLI
returns a safe typed error rather than success, without emitting the raw URL or
private journal path. There is no automatic retry or cloud rollback. Do not
blindly repeat the public operation after this error; the remote effect may
already exist, and a post-replacement error may also leave the new local record.

Формат:

```json
{"version":1,"recorded_at":"2026-07-24T13:00:00+00:00","operation":"publish","remote_path":"/Hermes/public/report.pdf","public_url":"[REDACTED]","public_url_fingerprint":"sha256:..."}
```

`public_url` хранится только в owner-private журнале; в документации, JSON-ответах,
логах и артефактах показывается только fingerprint или `[REDACTED]`. Журнал не
является источником истины Mail.ru. Это локальная история операций утилиты.

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
HMC_TEST_ROOT=/TEST/hermes-mailcloud-<unique-run-id>
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
      "config_loaded": true,
      "rclone_installed": true,
      "rclone_version": "1.74.3",
      "remote_configured": true,
      "remote_listed": true,
      "cloud_access": true,
      "about_available": true
    },
    "capabilities": {
      "file_ops": "unknown",
      "public_link_create": "unknown",
      "public_link_unlink": "unknown"
    }
  }
}
```

Но `doctor` не должен показывать секреты. Default mode performs only the
documented metadata calls. The separately mutating `doctor --json --live --yes`
uses fresh generated `/TEST/hermes-mailcloud-*` roots and reports only their
paths, cleanup state, and redacted capability evidence.

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
