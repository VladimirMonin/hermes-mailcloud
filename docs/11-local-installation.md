# Local installation and student setup

This guide installs the **0.2.0** command-first package and an optional Hermes skill.
The package is distributed on GitHub, **not PyPI**. Credentials remain in the
user's existing rclone configuration or are configured separately; installation
never requires reading or copying their contents.

## 1. Prerequisites

- Python **>=3.12**; Python 3.12/3.13 are the qualification targets.
- For the recommended route, [uv](https://docs.astral.sh/uv/getting-started/installation/)
  installed and available in your shell. `uv tool` is a built-in uv subcommand,
  not another tool to install. Follow the official platform installer instructions,
  open a fresh terminal when needed, then check `uv --version`.
- Public HTTPS access for the GitHub wheel/Python dependencies and explicit rclone
  preparation, or verified local artifacts/caches for the corresponding offline steps.
- No repository clone or preinstalled rclone is needed for regular use. Git is
  needed only for the optional source/development route below.
- A Mail.ru external-application password is needed only when creating a new
  cloud connection, not to install the CLI or reuse an already configured connection.

### Install uv itself

If uv is not installed, the official standalone installers are available below;
review the linked installation instructions and approve executing downloaded code
before running them. This is an intentional user installation, not something the
cloud CLI performs implicitly.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

POSIX shell:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The PowerShell policy option applies to that installer process, not a permanent
policy change. Follow the installer output for shell discovery, open a fresh
terminal if needed, and run `uv --version`. Other official installation methods
are equally usable; Administrator rights are not a package-install prerequisite.

## 2. Install the non-editable CLI and dependency

For an agent's regular use, `uv tool` is recommended: it isolates dependencies and
provides a persistent command usable outside the checkout. It is convenient,
**not mandatory**, and neither uv nor uv tool is a backend/cloud requirement.
`uv run` in the checkout is a separate source/development workflow.

### Install from a release wheel

Use the exact pinned GitHub asset URL (do not substitute a bare registry name):

```console
uv tool install --python 3.12 https://github.com/VladimirMonin/hermes-mailcloud/releases/download/v0.2.0/hermes_mailcloud-0.2.0-py3-none-any.whl
hermes-mailcloud version
hermes-mailcloud --json setup
hermes-mailcloud --json doctor
```

`version` must report **0.2.0**. The source repository need not be kept locally.
For an intentional replacement of an older GitHub-wheel installation:

```console
uv tool install --force --python 3.12 https://github.com/VladimirMonin/hermes-mailcloud/releases/download/v0.2.0/hermes_mailcloud-0.2.0-py3-none-any.whl
hermes-mailcloud version
hermes-mailcloud --json setup
```

This explicitly changes the package source/version; do not assume an upgrade by
package name will discover a newer GitHub wheel on PyPI. Package replacement does
not migrate credentials or automatically update an already valid rclone copy.

Alternatively download the wheel and `SHA256SUMS` from the
[0.2.0 GitHub Release](https://github.com/VladimirMonin/hermes-mailcloud/releases/tag/v0.2.0).
Compare its local SHA-256 to the matching entry (PowerShell `Get-FileHash -Algorithm
SHA256` or POSIX `sha256sum`), then use the local wheel path as the install argument.
A checksum checks integrity, not independent publisher authenticity. Runtime
Python dependencies may come from package indexes; they and rclone are not bundled.

If `hermes-mailcloud` is not found, `uv tool dir --bin` locates the tool executable
directory. In PowerShell the installed command can be invoked without a PATH edit:

```powershell
& (Join-Path (uv tool dir --bin) 'hermes-mailcloud.exe') version
```

Optional `uv tool update-shell` changes shell command discovery; apply it only as
an intentional user-shell configuration action and open a new terminal afterwards.
It is not a global rclone/PATH prerequisite. See the
[official uv tools guide](https://docs.astral.sh/uv/guides/tools/).

### Alternatives and source use

A regular Python virtual environment is also supported; uv tool is not mandatory.
For example, with Python 3.12 available via the Windows Python launcher:

```powershell
py -3.12 -m venv .hmc-env
.\.hmc-env\Scripts\python.exe -m pip install https://github.com/VladimirMonin/hermes-mailcloud/releases/download/v0.2.0/hermes_mailcloud-0.2.0-py3-none-any.whl
.\.hmc-env\Scripts\hermes-mailcloud.exe version
.\.hmc-env\Scripts\hermes-mailcloud.exe --json setup
```

Use that environment's launcher thereafter. For source/development, clone the
public repository, enter it and use `uv sync` / `uv run`; or install an accepted
checkout non-editably with `uv tool install --python 3.12 .`. A checkout install
snapshots the selected files; it does not automatically select an accepted commit.
Do not use editable installations for the operational cloud command. Contributors
also follow the [repository privacy guidance](../README.md#repository-privacy).

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

CI targets Ubuntu/Windows × Python 3.12/3.13 with offline, build and clean-wheel
checks, including native journal/process boundaries; inspect the exact commit's
Actions results. Local 0.2.0 launcher/direct-API/fake-backed qualification uses
native Windows x64/Python 3.12 with elevation, not ordinary-user Windows.
Ordinary-user qualification remains incomplete. Earlier official default HTTPS
setup, managed discovery and real local-file rclone checks are retained for
unchanged installer behavior, not fresh 0.2.0 transport evidence. See the
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

Use an ordinary per-user agent/CLI context by default. Elevated test coverage is
not evidence that Administrator rights are required, nor proof of ordinary-user
compatibility. On a permission failure, diagnose the exact selected executable,
configuration/journal path and supported ACL boundary using redacted errors; do
not automatically relaunch the whole agent as Administrator.

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

Atomic replacement can retire a journal generation after a reader opens it.
A handle observed with zero links is never accepted: it is closed, and the
current path is reopened with full regular-file, link-count, owner and protected
DACL validation before reading. Hardlinks, reparse files and invalid security
remain refusals, not retirement retries. The first observed retirement permits
one immediate fresh validation; further retries share the original 50ms budget
without resetting it. Missing/expired reads after retirement fail closed rather
than returning an empty journal. This bounds retries, not OS or scheduler delay,
and does not guarantee progress under continuous replacement.

The journal flushes its private temporary file and performs same-directory
replacement. Windows flushing/replacement is not a promise of POSIX-equivalent
directory fsync or power-loss durability. An error before replacement preserves
the old bytes; an error after replacement may leave the new version, without a
rollback guarantee. A journal error after `publish`/`link` may follow an already
completed remote effect: there is no automatic write retry or cloud rollback.
See [failure after a public operation](08-configuration-and-secrets.md#failure-after-a-public-operation).

## 3. Configure Mail.ru separately

### Reuse an existing connection

There are **two different configuration files**. Application `--config` selects
HMC profiles/policy, not backend authentication storage. `RCLONE_CONFIG` selects
the separate rclone file and must be present in the **invoking process environment**.
Keep the matching existing application profile explicitly selected with `--profile`.
In 0.2.0, an omitted option uses `HMC_PROFILE`, then `default`;
explicit `--profile default` wins over the environment. For historical 0.1.0
assets, use the explicit option rather than assuming 0.2.0 behavior.
A default `remote_not_configured` refusal does not establish that saved credentials
are missing.

Use known locators without opening/copying secret file bodies. These are fictitious
non-secret paths; `work` must be a matching profile already in the chosen HMC file:

```powershell
$env:RCLONE_CONFIG = 'C:\CloudSettings\rclone.conf'
hermes-mailcloud --config 'C:\CloudSettings\hmc.toml' --profile work --json doctor
```

POSIX shell equivalent, scoped to this invocation:

```sh
RCLONE_CONFIG='/safe/cloud-settings/rclone.conf' hermes-mailcloud --config /safe/cloud-settings/hmc.toml --profile work --json doctor
```

The PowerShell assignment affects that process/session, not persistent settings.
Native agents should pass an argv array and that environment to the child process
rather than embed shell quoting inside arguments. Never request passwords/config
contents in chat or infer a need to re-enter credentials merely from a wrong default
selection. Diagnose readiness with the selected read-only doctor first.

### Create a new connection only when needed

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

### Verified installed boundary retained from alpha

Earlier installed-alpha checks exercised a per-user uv tool from a Windows agent
outside the checkout, with native argument arrays, JSON and exit-status checks and
the selected official rclone. With the matching application config/profile and
backend RCLONE_CONFIG, a bounded real Mail.ru check created its own directory,
uploaded files, used list/stat, downloaded and compared complete bytes and SHA-256,
renamed an object and confirmed removal of only its own objects. Initial default
connection refusal and later correctly selected connection success are distinct
observations. These are retained alpha checks, **not newly executed 0.1.0 cloud
qualification**. Windows checks were **elevated**; ordinary-user runtime has **not**
been qualified. This proves neither an Administrator requirement nor ordinary-user
support; do not automatically elevate the whole agent.

## 4. Basic use

```bash
hermes-mailcloud ls / --json
hermes-mailcloud stat /Hermes/private --json
hermes-mailcloud mkdir /Hermes/private/reports --json
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
hermes-mailcloud download /Hermes/private/report.pdf ./report.downloaded.pdf --json
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
hermes-mailcloud link /Hermes/public/report.pdf --json
```

`stat` accepts a file or directory path. `publish` uploads a local file; `link`
gets or creates a public link for an existing remote item. Both require the
public-root policy and owner-private journal. Normal JSON returns a fingerprint,
not the raw capability URL. An HTTP success may describe an HTML landing page,
not downloaded document bytes; direct-download resolution and revoke/unlink are
not shipped. See [agent integration](07-agent-integration.md) and
[public-link risks](09-known-risks.md#31-public-url-не-равен-direct-download-url).
These are user-operation examples, not a grant to mutate those paths in tests.

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

The 0.2.0 wheel exposes the supported Python
[`MailCloudApplication` interface](01-architecture.md#current-in-process-application-interface)
for all shipped operations: version/read/file/public plus `setup`, `doctor`,
`batch(document)` and `batch_file(Path)` — fifteen real methods. All CLI handlers
use that owner, without a legacy CLI execution route.
The historical immutable `v0.1.0` wheel predates this boundary.
For a Python consumer, install the exact accepted 0.2.0 wheel into that
consumer's environment; an operational uv tool has its own interpreter and does
not add imports to an unrelated Python process. Verify artifact/import provenance,
not just the version string. This does not require an HTTP server or a replacement
of the user's operational installation during development.

```bash
uv sync --locked --all-groups --all-extras
uv run pytest -q -m "not live"
uv run hermes-mailcloud --help
```

For checkout-based installations only, after an accepted update reaches the main
branch, refresh from that checkout explicitly (GitHub-wheel users use the pinned
replacement URL above):

```bash
git pull --ff-only
uv tool install --force --python 3.12 .
hermes-mailcloud --json setup
hermes-mailcloud version
hermes-mailcloud --json doctor
```

Keep operational use on the installed command and development experiments on `uv run`. This prevents a branch switch or unfinished edit from changing the CLI that has access to cloud data.
