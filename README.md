# Hermes MailCloud

Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.

> Status: **v0.1 in progress** — `ls`, `stat`, `mkdir`, `upload`, `download`,
> `mv`, `cp`, guarded `rm`, `publish`, and `link` use the typed rclone boundary;
> `publish`/`link` require an owner-private local link journal and return only a
> public-link fingerprint. `batch` validates a strict versioned JSON plan, supports
> zero-call dry-runs, and reports ordered partial failures. `doctor` now defaults
> to rclone/config/remote metadata checks; its generated `/TEST` probes require
> explicit `--live --yes` and report cleanup and capability evidence.
> Full documentation: `docs/`

## Quick start (development)

```bash
uv sync
uv run hermes-mailcloud --help
uv run pytest -q
uv run ruff check .
```

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