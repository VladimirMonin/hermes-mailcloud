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

The repository is private at the time of writing, so students need repository access before cloning.

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

Do not use `--editable` for the operational command. A non-editable tool remains on the accepted installed revision while development branches and uncommitted files change.

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
