# Local installation and student setup

This guide describes a stable, non-editable `hermes-mailcloud` command and an
optional Hermes skill. It does not contain Mail.ru credentials; every user
configures their own account through `rclone`.

## Current publication state

This is a private, unpublished `0.1.0a0` candidate. Its public PyPI, immutable
source, and skill-install routes are not currently available. They become valid
only after the owner approves public visibility and the annotated, never-moved
`v0.1.0a0` tag exists. The PyPI route also requires the protected GitHub `pypi`
environment with its required reviewer, a configured Trusted Publisher, and the
completed PyPI upload. These are future external prerequisites; this guide does
not create or assert any of them.

## 1. Prerequisites

- [`uv`](https://docs.astral.sh/uv/) in `PATH`.
- [`rclone`](https://rclone.org/install/) in `PATH`.
- A Mail.ru external-application password for the account being configured.
- Git only for the immutable source route or development route.

## 2. Future installation routes

### PyPI route for students and ordinary operators

Only after the release's PyPI upload is complete, install the exact tested alpha
version:

```bash
uv tool install --python 3.12 "hermes-mailcloud==0.1.0a0"
hermes-mailcloud version
hermes-mailcloud --json doctor
```

This pins the project version, not a transitive dependency graph. Keep the pin
until a later accepted release is deliberately chosen; to replace an existing
tool with a newly selected exact version, use `--force` with that new pin.

### Immutable source route for maintainers

Only after the public repository and immutable release tag exist, install from
that tag (or replace it with a full accepted commit ID), never from a moving
branch or bare checkout path:

```bash
uv tool install --python 3.12 \
  "git+https://github.com/VladimirMonin/hermes-mailcloud.git@v0.1.0a0"
```

An operational source install remains non-editable and retains the accepted VCS
identity. It is distinct from the development route below.

### Development route

Clone a working branch only to develop or smoke-test it. Before public
visibility, this requires access explicitly granted by the owner:

```bash
git clone https://github.com/VladimirMonin/hermes-mailcloud.git
cd hermes-mailcloud
uv sync --locked --all-groups --all-extras
uv run hermes-mailcloud --help
```

Do not treat `uv tool install .` from a changing checkout as an operational
install; branch switching or local edits would destroy the intended provenance.

## 3. Configure Mail.ru in rclone

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

## 4. Create the local CLI configuration

Create the user configuration:

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

Check the installed command and read-only cloud access:

```bash
hermes-mailcloud version
hermes-mailcloud --json doctor
```

The doctor result should report `config_loaded`, `rclone_installed`,
`remote_configured`, `remote_listed`, and `cloud_access` as `true`.

## 5. Basic use

```bash
hermes-mailcloud ls / --json
hermes-mailcloud upload ./report.pdf /Hermes/private/report.pdf --json
hermes-mailcloud download /Hermes/private/report.pdf ./report.downloaded.pdf --json
hermes-mailcloud publish ./report.pdf /Hermes/public/report.pdf --json --yes
```

Use `--dry-run` before writes when the command supports it. Destructive operations require exact paths and explicit confirmation. The complete command contract is in [`02-command-contract.md`](02-command-contract.md).

## 6. Install the optional Hermes skill from the immutable release tag

Only after the public `v0.1.0a0` tag exists, use the target Hermes profile's
shell or session. The commands operate on that active profile; they do not copy
to a fixed `~/.hermes` path. Inspect the exact immutable file before installing,
then read the active profile's local-skill list back:

```bash
hermes skills inspect \
  https://raw.githubusercontent.com/VladimirMonin/hermes-mailcloud/v0.1.0a0/skills/mailru-cloud/SKILL.md
hermes skills install --category productivity \
  https://raw.githubusercontent.com/VladimirMonin/hermes-mailcloud/v0.1.0a0/skills/mailru-cloud/SKILL.md
hermes skills list --source local
```

Start a fresh Hermes session or run `/reload-skills`. Then requests such as
“upload this to Mail.ru Cloud” or “download this from Mail Disk” can route
through the installed CLI.

## 7. Updates, public links, and support

PyPI users update only by selecting a later accepted exact release pin and
reinstalling with `uv tool install --force --python 3.12
"hermes-mailcloud==<accepted-version>"`. Source-route maintainers update only by
replacing the tag or full commit ID with an accepted immutable revision. Do not
use an automatic latest-version update, a branch name, or a bare development
checkout for the operational command.

Version 0.1 does not ship `unlink`, and no public-link revocation or invalidation
capability is verified. Treat a created public link as potentially durable until
the provider's own controls establish otherwise. Before a write, use `--dry-run`
when supported and read the [command contract](02-command-contract.md).

Route a problem to the responsible owner:

- **Project CLI, documentation, or packaging defects:** only after public
  visibility, open a [project GitHub issue](https://github.com/VladimirMonin/hermes-mailcloud/issues)
  with the command version, exit code, and redacted JSON diagnostics. Before
  then, use an owner-approved private channel.
- **rclone backend or configuration defects:** use upstream
  [rclone documentation and support](https://rclone.org/docs/).
- **Mail.ru account, service, quota, or access problems:** use official Mail.ru
  support.

Never put an rclone configuration, password, access token, cloud object name,
or raw public link in any request. Share only redacted diagnostics and
public-link fingerprints through an appropriate approved route.
