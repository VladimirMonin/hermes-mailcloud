---
applyTo: "pyproject.toml,uv.lock,src/**/*.py,schemas/**/*.json,.gitignore"
name: "CORE.Project"
description: "Project-wide environment, dependency, source, schema, and safety rules for Hermes MailCloud."
---

# CORE — Project rules

## Environment

- Python `>=3.12` is declared in `pyproject.toml`; use `uv` for dependency and command execution.
- Keep `pyproject.toml` and `uv.lock` synchronized. Do not introduce another dependency workflow without explicit user direction.
- The installed CLI entry point is `hermes-mailcloud = hermes_mailcloud.cli:app`.

## Repository boundaries

- Runtime source belongs in `src/hermes_mailcloud/`; tests belong in `tests/`; JSON schemas belong in `schemas/`.
- The current code is a Wave 0 Typer skeleton. Do not present commands described only in `docs/` as implemented.
- The documented v0.1 backend is an external `rclone` subprocess. Do not vendor rclone or copy GPL implementation code into this MIT repository.
- When a machine-readable response contract changes, update the relevant schema, focused tests, and documentation in the same change.

## Safety

- Credentials stay in rclone configuration or external secret mechanisms, never in source, CLI arguments, fixtures, docs, logs, or committed configuration.
- Do not commit `.env`, rclone config, `links.jsonl`, databases, cloud payloads, logs, caches, build output, or probe artifacts.
- Do not weaken confirmation, public-root, dangerous-file, or secret-sanitization policies described by accepted ADRs without an explicit contract change and tests.
- Live cloud access and state-changing operations require explicit user intent. Once the owner grants bounded Mail.ru test authority for the active program, carry it forward without per-card reauthorization unless provider, data class, cost, destructive scope, or target root changes.
- Every project-owned cloud mutation must use a unique descendant of `/TEST/`. Existing objects outside `/TEST` are metadata/list-only: never overwrite, move, publish, or delete them.
- Cleanup authority covers only objects created by the same run inside its `/TEST/<unique-run-id>/` subtree. Cleanup failure is reported explicitly and never widened to adjacent data.

## Baseline gates

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
git diff --check
```
