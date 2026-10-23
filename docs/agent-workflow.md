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

## Direct Pi development

For a user-approved direct Pi program, Oracle resolves material architecture/contract uncertainty and prepares an executable plan before coding. One coder implements coherent code/test slices; one independent reviewer owns the technical verdict, actual checks and affected documentation/instructions. Hermes may personally perform the initial documentation bootstrap, then acts only as a thin coordinator: it decides material rework, priorities and top-level dispatch, not implementation or a second technical review. Each worker reports actual results and remaining work to Hermes. Provider/model/thinking choices, assigned peer sessions, current scopes and run evidence stay in the authorized private handoff, not durable instructions. Creating a branch does not authorize stage/commit/push.

Assigned Pi peers may communicate directly through pi-intercom about intent, APIs, evidence, and concrete technical questions. Verify the assigned peer's session ID, working directory, and role before sending; use notifications for ordinary updates and finite-wait questions only for genuine blockers. Transport delivery to a busy peer does not prove model receipt or agreement: do not resend repeatedly, create another session, or build mutual busy-worker waits; return unresolved coordination to Hermes. Horizontal communication does not expand write scopes, authorize excluded actions, or create an independent assignment pipeline.

1. Oracle prepares the executable architectural plan with current/proposed boundaries, scope, seams, compatibility, safe diagnostics, tests and acceptance criteria. Consult the same Oracle again for substantial uncertainty or repeated failure, not every minor fix. Split the roadmap into coherent independently verifiable slices, not one-file tasks.
2. The coder implements and tests within that scope, reports actual checks and remaining limitations, then freezes all candidate writes and test runs. Self-checks are evidence for review, not independent acceptance.
3. The reviewer inspects the composed behavior and runs fresh relevant checks, including seam/integration tests. Missing target-platform evidence is reported as missing, not inferred from another OS or old CI. Concrete FAIL/findings return to Hermes for material rework and priority decisions; the reviewer does not independently assign the coder another stage. Hermes-dispatched bounded corrections continue the same coder session, followed by delta review. Unmet mandatory criteria cannot be reported as PASS; preferences alone do not justify endless mandatory rework.
4. After PASS, the reviewer completes affected documentation/instructions and their checks, then stages exact accepted paths and makes the already-authorized local scoped commit without another per-commit permission request. The coder never owns the index or commits. Push requires its separate explicit grant; when that grant requires delivery, the same reviewer pushes the frozen accepted SHA to the verified ref and reads it back before reporting delivery. No commit-only extra agent is needed.
5. After independent acceptance and any required, separately authorized save/delivery, Hermes dispatches the next top-level slice. No commit is required when there is no commit grant. The reviewer may maintain documentation/instructions concurrently on explicitly non-overlapping paths. One index owner stages only accepted changes within its grant; a dirty tree from disjoint in-flight work is not permission to include it.

This route needs no new Kanban cards and does not reassign existing Kanban work. Documentation must describe what the accepted code actually supports; test counts, run reports, and temporary evidence do not belong in durable docs.

## Project-local methodology

The complete [Project Foundation Kit](../tools/project-foundation/README.md) is a
read-only methodological dependency. Adapted project rules take precedence. For an
explicit Pi resource selection, run from this repository and use `--no-skills`
with `--skill ./tools/project-foundation/skills/pf-command-first/SKILL.md` (or the
matching `pf-plan` / `pf-quality` path). This changes resource selection only; it
does not isolate the filesystem, disable extensions, or authorize cloud access.
No global settings change is necessary. Verify the actual selected file and read
its required linked resources; an available slash-command alone is not proof of use.

Oracle, coder and reviewer have separate saved conversations even if models match.
Use codebase-memory, Serena and ast-grep where useful, establishing project root
and index freshness before relying on indexed absence. Private/runtime paths stay
excluded; internal readers inherit the same read-only/source boundaries. Do not
create a second progress-log system inside public documentation.

## Quality and Git boundary

Run the smallest relevant offline checks, then the applicable gates in `instructions/TEST.quality_gates.instructions.md`. Live tests, probes, and cloud mutations are opt-in. For documentation/instruction-only changes, check meaning, affected routing/links, and whitespace; do not install runtime dependencies or run the full Python suite merely for a docs bootstrap.

Before any authorized commit, inspect status, unstaged/untracked changes, and the staged diff separately. The commit message must describe only the staged diff and use a conventional prefix. Explicit authorization may cover the reviewer's accepted local commits for a program; commit permission never implies push permission. Preserve the configured public GitHub noreply identity and never expose personal email values; see `instructions/DOCS.git.instructions.md`.
