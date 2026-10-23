# AGENTS.md — Hermes MailCloud

Read this file first, then every matching file in `instructions/` before editing.

## Project identity

`hermes-mailcloud` is a Python 3.12+ application for safe Mail.ru Cloud operations, currently exposed through a JSON-first CLI backed by an external `rclone` subprocess. The engineering direction is **command-first**: application operations and safety rules must be usable without Typer, a terminal, GUI, or MCP. A plan is not an implemented API.

Read [project philosophy](docs/foundation/project-philosophy.md) for priorities and [architecture principles](docs/foundation/architecture-principles.md) before changing application boundaries. Current CLI contracts remain in `docs/02-command-contract.md` and `schemas/`.

Confirmed project facts:

- dependencies and commands are managed with `uv` and the committed `uv.lock`;
- source lives in `src/hermes_mailcloud/` and tests in `tests/`;
- schemas are under `schemas/`, while architecture and proposed contracts are under `docs/`;
- current-source `hermes_mailcloud.application` exposes all shipped operations through `MailCloudApplication`, including `setup`, `doctor`, `batch(document)` and `batch_file(Path)` alongside version/read/file/public methods; all shipped CLI handlers use that owner. Private transitional glue is not a supported fallback. See the [current application interface](docs/01-architecture.md#current-in-process-application-interface); an older release wheel does not gain it from a matching version string;
- live cloud tests are opt-in and require explicit environment configuration.

## Commands

```bash
uv sync --locked --all-groups --all-extras
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
7. Commit and push require separate explicit user authorization. An approved implementation program may authorize the designated reviewer to make local scoped commits after PASS; it does not authorize push.
8. For direct Pi development, Oracle investigates material architectural uncertainty and prepares an executable plan; one coder implements coherent code/test slices; one independent reviewer owns technical acceptance and affected documentation/instructions. Hermes becomes a thin coordinator after the documentation bootstrap: it dispatches, resolves priorities, and routes findings to the same owners, without implementing or supplying a second technical review. The coder does not stage or commit. The reviewer may make scoped local commits only under an explicit current grant. Keep model choices, peer sessions and run evidence in private handoffs, not durable instructions; see `docs/agent-workflow.md`.
9. Direct Pi development does not require new Kanban cards or changes to existing assignments. Tiny documentation/instruction corrections may be made directly by the designated reviewer with only affected checks; existing Kanban work retains its own routing.
10. A blocker is a demonstrated condition that cannot be resolved safely inside the approved scope: unavailable credentials after the real bootstrap, risk to existing user data, an ambiguous external side effect, a frozen-contract conflict, or exhausted safe repair strategies. Routine review, tests, documentation sync, and already-approved Mail.ru access are not blockers.
11. All project-owned Mail.ru test mutations are confined to `/TEST/<unique-run-id>/`. Existing objects outside `/TEST` are read-only and must never be overwritten, moved, published, or deleted.

## Instruction routing

| Work area | Read |
|---|---|
| Setup, dependencies, repository boundaries, safety | `instructions/CORE.project.instructions.md` |
| Tests, lint, format, offline/live quality gates | `instructions/TEST.quality_gates.instructions.md` |
| Diagnostics, redaction, stderr, logging or telemetry | `instructions/LOG.observability.instructions.md` |
| README, `docs/`, ADRs, AGENTS and instruction maintenance | `instructions/DOCS.documentation.instructions.md` |
| Hermes Kanban work for board `hermes-mailcloud` | `instructions/AGENT.kanban.instructions.md` |
| Staging, commit messages, secret/artifact checks, push | `instructions/DOCS.git.instructions.md` |

Human documentation starts at `README.md`; the documentation index is `docs/README.md`. Instruction maintenance is described in `docs/agent-workflow.md`.

## Project Foundation Kit

The complete methodological package is vendored in `tools/project-foundation/`. Treat it as a read-only reference, not a second project-instruction authority. Read its `README.md`, then only the matching skill: `pf-bootstrap` for instruction adoption, `pf-plan` and `pf-command-first` for architecture, `pf-quality` for tests/diagnostics. Resolve resource links relative to the selected skill. Existing project rules, contracts and safety boundaries take precedence. Do not change global Pi/Hermes settings to use this package.

## Git discipline

The staged diff is the only source for a commit message. Inspect status, unstaged changes, untracked files, and the staged diff before committing. Use conventional prefixes; never stage secrets or local/generated artifacts. See `instructions/DOCS.git.instructions.md`.
