# Agent instruction workflow

The repository uses `AGENTS.md` as a router and `instructions/*.instructions.md` as atomic durable rules.

## Reading rules

1. Read `AGENTS.md` before editing.
2. Read every instruction whose `applyTo` scope or routing description matches the files or behavior being changed.
3. Inspect current source, tests, `pyproject.toml`, schemas, relevant docs, and accepted ADRs before relying on a documented contract.
4. Treat planned Wave behavior as design intent until current code and tests confirm it.

## Adding or changing instructions

Add a rule only when it is durable, repeatedly useful, and project-wide or attached to a confirmed subsystem boundary. Each instruction file must remain focused and include:

```yaml
---
applyTo: "matching/globs/**"
name: "CATEGORY.Name"
description: "When this instruction applies."
---
```

Prefer updating an existing atomic file over creating overlapping rules. When routing changes, synchronize `AGENTS.md`, `docs/README.md`, and `docs/agent-workflow.md` as needed. Do not store card IDs, progress, reports, test counts, session notes, or implementation history in instructions.

## Quality and Git boundary

Run the smallest relevant offline checks, then the applicable gates in `instructions/TEST.quality_gates.instructions.md`. Live tests, probes, and cloud mutations are opt-in.

Before any requested commit, inspect status, unstaged/untracked changes, and the staged diff. The commit message must describe only the staged diff and use a conventional prefix. Commit and push are separate actions and each requires explicit user authorization; see `instructions/DOCS.git.instructions.md`.
