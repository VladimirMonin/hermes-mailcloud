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

## Quick start (development)

```bash
uv sync --locked --all-groups --all-extras
uv run hermes-mailcloud --help
uv run hermes-mailcloud version
uv run pytest -q -m "not live"
uv run ruff check .
```

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