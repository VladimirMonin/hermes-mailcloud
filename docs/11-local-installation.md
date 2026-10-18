# Local installation and student setup

This guide installs a stable, non-editable `hermes-mailcloud` command and an optional Hermes skill. It does not contain Mail.ru credentials; every user configures their own account through `rclone`.

## 1. Prerequisites

- Git access to this repository.
- [`uv`](https://docs.astral.sh/uv/) in `PATH`.
- [`rclone`](https://rclone.org/install/) in `PATH`.
- A Mail.ru external-application password for the account being configured.

Clone the repository and enter it:

```bash
git clone https://github.com/VladimirMonin/hermes-mailcloud.git
cd hermes-mailcloud
```

The repository is public and can be cloned without a repository invitation.
Before contributing, configure a GitHub-provided noreply address for this
repository and follow the [repository privacy guidance](../README.md#repository-privacy).

## 2. Configure Mail.ru in rclone

Run:

```bash
rclone config
```

Create a Mail.ru Cloud remote named `mailru`. Store the account login and external-application password only in the private rclone configuration. Do not put credentials in this repository or in the `hermes-mailcloud` config.

Verify the remote:

```bash
rclone lsd mailru:
rclone about mailru:
```

See [`08-configuration-and-secrets.md`](08-configuration-and-secrets.md) for the full credential and configuration boundary.

## 3. Install the stable CLI

From the repository root:

```bash
uv tool install --python 3.12 .
```

Do not use `--editable` for the operational command. Install from accepted package
sources, not a checkout with in-flight code changes: the command snapshots the
selected sources, it does not automatically select an accepted Git commit. That
non-editable installation then stays unchanged while later development moves on.

Python `>=3.12` is required. On native Windows, dependency resolution includes
`pywin32>=312` via the `sys_platform == 'win32'` marker; the repository lockfile
selects `312`. Do not copy bindings manually or use MSYS/WSL permission emulation
as a replacement for native Windows ACLs. Linux does not require pywin32.
See [third-party notices](../THIRD_PARTY_NOTICES.md#pywin32-notices).

Native journal and fake-backed command checks do not establish complete Windows
qualification. Ordinary non-admin Windows execution, the full target Python/OS
matrix, remaining subprocess-tree/file-command work and clean installed-wheel/
console-launcher qualification still need validation. The install command above
is an installation procedure, not evidence that those gates passed or that a
real rclone/Mail.ru account was exercised.

On POSIX, create a new user configuration (edit an existing file instead of
overwriting it):

```bash
mkdir -p ~/.config/hermes-mailcloud
cat > ~/.config/hermes-mailcloud/config.toml <<'EOF'
[profiles.default]
remote = "mailru:"
rclone_path = "rclone"
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

Use a native `rclone.exe`, optionally an explicit executable path via
`HMC_RCLONE_PATH`; that value is one executable, not a shell command with arguments.

### Windows storage limits

The journal flushes its private temporary file and performs same-directory
replacement. Windows flushing/replacement is not a promise of POSIX-equivalent
directory fsync or power-loss durability. An error before replacement preserves
the old bytes; an error after replacement may leave the new version, without a
rollback guarantee. A journal error after `publish`/`link` may follow an already
completed remote effect: there is no automatic write retry or cloud rollback.
See [failure after a public operation](08-configuration-and-secrets.md#failure-after-a-public-operation).

Check the installed command and read-only cloud access after configuring your
own rclone remote:

```bash
hermes-mailcloud version
hermes-mailcloud --json doctor
```

The doctor result should report `config_loaded`, `rclone_installed`, `remote_configured`, `remote_listed`, and `cloud_access` as `true`.

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
hermes-mailcloud version
hermes-mailcloud --json doctor
```

Keep operational use on the installed command and development experiments on `uv run`. This prevents a branch switch or unfinished edit from changing the CLI that has access to cloud data.
