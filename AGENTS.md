# AGENTS.md — Hermes MailCloud project router

Read this file first, then every matching file in `instructions/` before editing.

## Project identity

`hermes-mailcloud` is a Python 3.12+ agent CLI for Mail.ru Cloud. The current implementation is a Wave 0 Typer skeleton; the documented target architecture is JSON-first and delegates cloud operations to an external `rclone` subprocess.

Confirmed project facts:

- dependencies and commands are managed with `uv` and the committed `uv.lock`;
- source lives in `src/hermes_mailcloud/` and tests in `tests/`;
- schemas are under `schemas/`, while architecture and proposed contracts are under `docs/`;
- live cloud tests are opt-in and require explicit environment configuration.

## Commands

```bash
uv sync
uv lock --check
uv run hermes-mailcloud --help
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
git diff --check
```

Run the smallest relevant offline test first. Do not run live tests or probes by default.

## Hard rules

1. Use `uv`; keep `pyproject.toml` and `uv.lock` synchronized.
2. Treat `docs/` plans as design intent until behavior is confirmed by current source and tests.
3. Preserve machine-readable CLI contracts and safety gates when they are implemented; update schemas, tests, and documentation together.
4. Never expose or commit credentials, `.env`, rclone configuration, cloud data, public-link journals, databases, logs, caches, or generated probe artifacts.
5. Cloud-mutating operations, live tests, and probes require explicit user intent and isolated test paths.
6. Do not create status, history, session-report, or progress-report documents.
7. Commit and push only on explicit user request.
8. Terra implements bounded stage slices; Sol/default independently reviews each stage and owns accepted scoped commits. Implementation and review workers do not commit.
9. Do not create Kanban cards for one-to-three-line documentation, instruction, wording, routing, formatting, or control-plane fixes that do not change product semantics, security, schemas, privacy, integrity, or dependencies. Sol/default fixes those directly and reruns only affected checks.
10. A blocker is a demonstrated condition that cannot be resolved safely inside the approved scope: unavailable credentials after the real bootstrap, risk to existing user data, an ambiguous external side effect, a frozen-contract conflict, or exhausted safe repair strategies. Routine review, tests, documentation sync, and already-approved Mail.ru access are not blockers.
11. All project-owned Mail.ru test mutations are confined to `/TEST/<unique-run-id>/`. Existing objects outside `/TEST` are read-only and must never be overwritten, moved, published, or deleted.

## Instruction routing

| Work area | Read |
|---|---|
| Setup, dependencies, repository boundaries, safety | `instructions/CORE.project.instructions.md` |
| Tests, lint, format, offline/live quality gates | `instructions/TEST.quality_gates.instructions.md` |
| README, `docs/`, ADRs, AGENTS and instruction maintenance | `instructions/DOCS.documentation.instructions.md` |
| Hermes Kanban work for board `hermes-mailcloud` | `instructions/AGENT.kanban.instructions.md` |
| Staging, commit messages, secret/artifact checks, push | `instructions/DOCS.git.instructions.md` |

Human documentation starts at `README.md`; the documentation index is `docs/README.md`. Instruction maintenance is described in `docs/agent-workflow.md`.

## Git discipline

The staged diff is the only source for a commit message. Inspect status, unstaged changes, untracked files, and the staged diff before committing. Use conventional prefixes; never stage secrets or local/generated artifacts. See `instructions/DOCS.git.instructions.md`.
