# Local installation and student setup

This guide installs a stable, non-editable `hermes-mailcloud` command and an optional Hermes skill. It does not contain Mail.ru credentials; every user configures their own account through `rclone`.

## 1. Prerequisites

- Git access to this repository.
- [`uv`](https://docs.astral.sh/uv/) in `PATH`.
- Official HTTPS access for explicit dependency preparation, or the matching
  pinned official archive for offline setup. No preinstalled rclone/PATH step.
- A Mail.ru external-application password only for the separate cloud-account
  configuration, not package installation or dependency setup.

Clone the repository and enter it:

```bash
git clone https://github.com/VladimirMonin/hermes-mailcloud.git
cd hermes-mailcloud
```

The repository is public and can be cloned without a repository invitation.
Before contributing, configure a GitHub-provided noreply address for this
repository and follow the [repository privacy guidance](../README.md#repository-privacy).

## 2. Install the stable CLI and dependency

From the repository root:

```bash
uv tool install --python 3.12 .
hermes-mailcloud --json setup
hermes-mailcloud --json doctor
```

Do not use `--editable` for the operational command. Install from accepted package
sources, not a checkout with in-flight code changes: the command snapshots the
selected sources, it does not automatically select an accepted Git commit. That
non-editable installation then stays unchanged while later development moves on.

### Prepare rclone

The agent explicitly runs `hermes-mailcloud setup` after installing the Python
package. No user-supplied executable or PATH editing is required. Default setup
uses official HTTPS, pinned archive/executable SHA-256 and sizes, exact-member
extraction and a private staged version check before atomic activation. It only
prepares rclone: no account/cloud configuration, package-install hook, global
PATH/registry/service change or implicit download from ordinary commands.

The packaged pin is **rclone v1.75.2**, Windows/Linux **amd64 with 64-bit Python**.
The artifact minimums checked by setup are Windows 10 / Server 2016+ or Linux
kernel 3.2+; other OSes/architectures are rejected. Actual local qualification is
Windows 11 x64/Linux with Python 3.12/3.13, not every upstream-supported platform.
Windows managed storage also requires the supported local fixed NTFS/private
path form, not redirected network/reparse storage. Do not weaken permissions to
bypass a refusal. The downloaded rclone remains a separate external MIT tool;
it is not included in the Python wheel/sdist. See [third-party notices](../THIRD_PARTY_NOTICES.md)
and the [official downloads](https://rclone.org/downloads/).

Managed storage is `%LOCALAPPDATA%/hermes-mailcloud/rclone` on Windows (falling
back to `USERPROFILE`/`HOME` plus `AppData/Local` when needed), or
`${XDG_DATA_HOME:-$HOME/.local/share}/hermes-mailcloud/rclone` on Linux. It is
separate from site-packages and cloud configuration. Protected staging, a stable
setup lock and a verified activation record support repeated/concurrent setup;
old release files are retained on error, without a rollback promise after an
already-completed atomic replacement.

For offline preparation, the agent can reuse the exact official archive matching
packaged `hermes_mailcloud/rclone/releases.json`; arbitrary URLs/versions are not
accepted. The ZIP is verified just as in the default HTTPS path:

```console
hermes-mailcloud --json setup --archive /absolute/path/to/pinned-official.zip
hermes-mailcloud --json setup --dry-run
```

Dry-run does not download, launch a process or create managed directories.
A valid external rclone is kept; otherwise an already verified managed generation
is reused, not automatically updated when the Python package pin changes. Explicit
`HMC_RCLONE_PATH` or profile `rclone_path` always wins, including an invalid path:
correct that override separately, never silently replace it. Omit `rclone_path`
for automatic external-PATH → managed lookup. Read-only doctor may suggest setup
but never performs it. After setup alone, `rclone_installed` can be true while
`remote_configured`/`cloud_access` remain false; this is not a setup failure.

Python `>=3.12` is required. On native Windows, dependency resolution includes
`pywin32>=312` via the `sys_platform == 'win32'` marker; the repository lockfile
selects `312`. Do not copy bindings manually or use MSYS/WSL permission emulation
as a replacement for native Windows ACLs. Linux does not require pywin32.
See [third-party notices](../THIRD_PARTY_NOTICES.md#pywin32-notices).

Local clean-wheel, real console-launcher and fake-backed file/public/batch
checks cover Windows/Linux with Python 3.12 and 3.13, including the native journal
and subprocess boundary. The Windows checks used elevated processes: genuine
ordinary-user Windows qualification and a remote GitHub Actions matrix remain
unqualified. Official default HTTPS setup, managed discovery and real local-file
rclone use are checked separately from fake-backed scenarios. See the
[portable package smoke](../README.md#package-smoke-test) for isolated wheel
validation; it is distinct from installing the operational command above and
does not prove Mail.ru access or complete release readiness.

On POSIX, create a new user configuration (edit an existing file instead of
overwriting it):

```bash
mkdir -p ~/.config/hermes-mailcloud
cat > ~/.config/hermes-mailcloud/config.toml <<'EOF'
[profiles.default]
remote = "mailru:"
# Omit rclone_path to use external-PATH -> managed lookup.
links_journal = "~/.local/share/hermes-mailcloud/links.jsonl"
EOF
chmod 600 ~/.config/hermes-mailcloud/config.toml
```

### Windows configuration

The Bash/chmod example above is POSIX-only. On Windows, create the same
`[profiles.default]` configuration in a text editor as UTF-8 **without BOM**,
creating its parent directory as needed. Do not overwrite an existing profile.
For a new configuration, `links_journal` may be omitted if the explicit environment
override below is used. In PowerShell:

```powershell
$env:HMC_CONFIG = Join-Path $env:USERPROFILE '.config\hermes-mailcloud\config.toml'
$env:HMC_LINKS_JOURNAL = Join-Path $env:USERPROFILE 'MailCloudData\private-state\links.jsonl'
```

These variables affect this PowerShell session; they do not create the config
file or change the platform default. Leave the new `private-state` directory
absent so the journal backend creates its protected DACL itself. The path must
be on local fixed NTFS with no reparse/alias components; choose another writable
local path if the profile is redirected. Do not weaken ACLs or treat elevation
as a portability fix. The full supported form and threat model are in
[Windows journal boundary](08-configuration-and-secrets.md#windows-journal-boundary).

### Windows subprocess boundary

Use a native `rclone.exe`. Profile `rclone_path` and `HMC_RCLONE_PATH` each name
one executable, not a shell command or an argv list. Use an absolute path, or a
bare name such as `rclone`/`rclone.exe` resolved only through absolute entries in
the runner's supplied `PATH`. The runner adds `.exe` when absent; it does not
implicitly search the working directory or use `PATHEXT`. Relative executable
paths and `.bat`/`.cmd`/script wrappers are not supported. Arguments remain
separate literal values; do not add shell quoting inside the configured path.

The native runner creates the process suspended, assigns it to a non-breakaway
Job Object with kill-on-close, then resumes it. Parent exit alone is not
completion: the Job must be empty and both output pipes drained to EOF, with
bounded capture. On timeout or supervision failure it attempts bounded tree
termination and cleanup. If cleanup cannot be confirmed, it returns a safe typed
`unknown_error`, not success or a claim of clean timeout; raw OS/backend diagnostics
are not exposed. A timeout or cleanup error does not prove that a remote effect
did not occur and does not roll it back. Writes are not automatically retried.
POSIX execution retains its separate process-group cleanup.

### Windows storage limits

The journal flushes its private temporary file and performs same-directory
replacement. Windows flushing/replacement is not a promise of POSIX-equivalent
directory fsync or power-loss durability. An error before replacement preserves
the old bytes; an error after replacement may leave the new version, without a
rollback guarantee. A journal error after `publish`/`link` may follow an already
completed remote effect: there is no automatic write retry or cloud rollback.
See [failure after a public operation](08-configuration-and-secrets.md#failure-after-a-public-operation).

## 3. Configure Mail.ru separately

Dependency setup does not create or change an rclone remote. After the preceding
installation, the agent starts upstream interactive `rclone config` using the
already selected external/managed executable, not a second global installation.
Installation automation can resolve it with `hermes_mailcloud.config.resolve_config().rclone_path`
in the **same installed Python environment**, never an in-flight checkout. Here
`rclone config` names the upstream command, not a promise that a managed binary
is on PATH; the user is not asked to locate it. Enter credentials directly into
rclone's interactive configuration, not command arguments or chat.

Create a Mail.ru Cloud remote named `mailru`. Keep login/app password only in
its private rclone configuration, not in the repository or HMC profile. After
that separate account step, verify readiness through the ordinary installed CLI:

```bash
hermes-mailcloud version
hermes-mailcloud --json doctor
```

Only after successful account configuration/access should `config_loaded`,
`rclone_installed`, `remote_configured`, `remote_listed` and `cloud_access` all be
true. Read-only doctor does not configure or mutate the cloud. See
[configuration and secrets](08-configuration-and-secrets.md).

## 4. Basic use

```bash
hermes-mailcloud ls / --json
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
hermes-mailcloud download /Hermes/private/report.pdf ./report.downloaded.pdf --json
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

Use `--dry-run` before writes when the command supports it. Destructive operations require exact paths and explicit confirmation. The complete command contract is in [`02-command-contract.md`](02-command-contract.md).

## 5. Install the optional Hermes skill

The repository includes a compact agent router at [`../skills/mailru-cloud/SKILL.md`](../skills/mailru-cloud/SKILL.md). Copy it into the current Hermes profile:

```bash
install -Dm644 skills/mailru-cloud/SKILL.md \
  ~/.hermes/skills/productivity/mailru-cloud/SKILL.md
```

Start a fresh Hermes session or run `/reload-skills`, then requests such as “upload this to Mail.ru Cloud” or “download this from Mail Disk” can route through the installed CLI.

## 6. Development and updates

Use the checkout only for development:

```bash
uv sync --locked --all-groups --all-extras
uv run pytest -q -m "not live"
uv run hermes-mailcloud --help
```

After an accepted update reaches the main branch, refresh the stable command explicitly:

```bash
git pull --ff-only
uv tool install --force --python 3.12 .
hermes-mailcloud --json setup
hermes-mailcloud version
hermes-mailcloud --json doctor
```

Keep operational use on the installed command and development experiments on `uv run`. This prevents a branch switch or unfinished edit from changing the CLI that has access to cloud data.
