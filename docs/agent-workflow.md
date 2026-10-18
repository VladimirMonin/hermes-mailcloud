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

For a user-approved direct Pi program, one coder implements broad, coherent code/test slices and one independent designated reviewer owns the technical verdict, actual checks, authorized local scoped commits, documentation, and instructions. Hermes is a thin coordinator, not another implementation or technical review owner; it decides material rework, priorities, and the next top-level dispatch. Each worker reports its results, findings, actual commit, and remaining work to Hermes. Provider/model routes, assigned peer session IDs, current slice scopes, and handoffs stay in the authorized local plan rather than durable instructions.

Assigned Pi peers may communicate directly through pi-intercom about intent, APIs, evidence, and concrete technical questions. Verify the assigned peer's session ID, working directory, and role before sending; use notifications for ordinary updates and finite-wait questions only for genuine blockers. Transport delivery to a busy peer does not prove model receipt or agreement: do not resend repeatedly, create another session, or build mutual busy-worker waits; return unresolved coordination to Hermes. Horizontal communication does not expand write scopes, authorize excluded actions, or create an independent assignment pipeline.

1. The reviewer prepares an executable slice with a concrete outcome, write scope, seams, tests, and acceptance criteria. Do not turn the whole roadmap into one packet or split implementation into one-file tasks.
2. The coder implements and tests within that scope, reports actual checks and remaining limitations, then freezes all candidate writes and test runs. Self-checks are evidence for review, not independent acceptance.
3. The reviewer inspects the composed behavior and runs fresh relevant checks, including seam/integration tests. Missing target-platform evidence is reported as missing, not inferred from another OS or old CI. Concrete FAIL/findings return to Hermes for material rework and priority decisions; the reviewer does not independently assign the coder another stage. Hermes-dispatched bounded corrections continue the same coder session, followed by delta review. Unmet mandatory criteria cannot be reported as PASS; preferences alone do not justify endless mandatory rework.
4. Only after PASS does the reviewer stage exact accepted paths and make the already-authorized local scoped commit, without another per-commit permission request. The coder never owns the index or commits. Push remains separately authorized.
5. After the accepted code commit, Hermes dispatches the next top-level code slice. The reviewer may maintain documentation/instructions concurrently on explicitly non-overlapping paths. One index owner stages only that owner's accepted changes; a dirty tree from disjoint in-flight work is not permission to include it.

This route needs no new Kanban cards and does not reassign existing Kanban work. Documentation must describe what the accepted code actually supports; test counts, run reports, and temporary evidence do not belong in durable docs.

## Quality and Git boundary

Run the smallest relevant offline checks, then the applicable gates in `instructions/TEST.quality_gates.instructions.md`. Live tests, probes, and cloud mutations are opt-in. For documentation/instruction-only changes, check meaning, affected routing/links, and whitespace; do not install runtime dependencies or run the full Python suite merely for a docs bootstrap.

Before any authorized commit, inspect status, unstaged/untracked changes, and the staged diff separately. The commit message must describe only the staged diff and use a conventional prefix. Explicit authorization may cover the reviewer's accepted local commits for a program; commit permission never implies push permission. Preserve the configured public GitHub noreply identity and never expose personal email values; see `instructions/DOCS.git.instructions.md`.
