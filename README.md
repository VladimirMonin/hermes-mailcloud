# Hermes MailCloud

Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.

> Status: **Wave 0 — project bootstrap**  
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

## Architecture

```
Hermes Agent → hermes-mailcloud CLI → policy + JSON contract → rclone subprocess → Mail.ru Cloud
```

See `docs/01-architecture.md` and `docs/03-development-plan.md` for the full plan.