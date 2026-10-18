# Hermes MailCloud

Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.

> Status: **v0.1 pre-release package** — `version`, `doctor`, `ls`, `stat`,
> `mkdir`, `upload`, `download`, `mv`, `cp`, guarded `rm`, `publish`, `link`,
> and `batch` are implemented through the typed rclone boundary. `publish`/`link`
> require an owner-private local link journal and return only a public-link
> fingerprint. `batch` validates a strict versioned JSON plan, supports zero-call
> dry-runs, and reports ordered partial failures. `doctor` defaults to read-only
> rclone/config/remote checks; generated `/TEST` probes require `--live --yes`.
> `unlink`, direct-download resolution, link expiry/passwords, and a full link
> audit are not shipped in v0.1.
> Full documentation: `docs/`

## Version and platform support

The `v0.1.0a0` tag identifies the `0.1.0a0` alpha source snapshot. A source
tag is not a GitHub Release, a PyPI upload, or a claim of production readiness.
The current implementation targets Linux. Native Windows execution is not yet
supported because the link journal uses POSIX-only file locking and filesystem
operations; creating this tag does not resolve that limitation.

## Quick start (development)

```bash
uv sync --locked --all-groups --all-extras
uv run hermes-mailcloud --help
uv run hermes-mailcloud version
uv run pytest -q -m "not live"
uv run ruff check .
```

## Install for daily use

Install a stable, non-editable command from an accepted repository revision:

```bash
uv tool install --python 3.12 .
hermes-mailcloud version
hermes-mailcloud --json doctor
```

Mail.ru credentials remain in the user's private `rclone` configuration. The
complete student setup, local config, skill installation, and update procedure
are in [`docs/11-local-installation.md`](docs/11-local-installation.md).

## Package smoke test

Build and install the wheel into a fresh virtual environment. This smoke test
does not use a Mail.ru credential or run a live probe; `doctor --json` remains
read-only.

```bash
uv build
smoke_dir="$(mktemp -d)"
uv venv "$smoke_dir/venv" --python 3.12
uv pip install --python "$smoke_dir/venv/bin/python" dist/*.whl
smoke_env=(env -i PATH="$PATH" HOME="$smoke_dir/home" XDG_CONFIG_HOME="$smoke_dir/config")
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" --help
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" version
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" --json doctor
rm -rf "$smoke_dir"
```

GitHub Actions runs the same lock, lint, format, offline-test, build, and clean
wheel-smoke gates without Mail.ru credentials or live tests.

## Live tests (require real rclone + Mail.ru remote)

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live
```

The live file suite creates and removes only one fresh `/TEST/hermes-mailcloud-*`
root (or a validated `HMC_TEST_ROOT` override); it never uses existing cloud data.
`hermes-mailcloud doctor --json` is read-only. `doctor --json --live --yes` is a
separate opt-in diagnostic that uses fresh generated `/TEST/hermes-mailcloud-*`
roots and leaves existing cloud data metadata/list-only.

## Architecture

```
Hermes Agent → hermes-mailcloud CLI → policy + JSON contract → rclone subprocess → Mail.ru Cloud
```

See `docs/01-architecture.md` and `docs/03-development-plan.md` for the full plan.

## Repository privacy

Use the GitHub-provided noreply address from your account's email settings for
both author and committer identities. Configure it for this repository before
creating commits or annotated tags; changing Git's display with `.mailmap` does
not remove an address from existing commit objects.

Keep credentials, real cloud data, capability URLs, and machine-specific home
paths out of tracked files and commit or tag messages. Review metadata as well
as file content before publishing; a clean secret scan is not a complete
personal-data check.

After a maintainer announces a privacy-related history rewrite, use a fresh
clone. Preserve and inspect any uncommitted work separately before moving it;
do not merge or push old branches back into the cleaned history. Rewriting
repository history cannot erase existing external clones or guarantee removal
of cached commit views.