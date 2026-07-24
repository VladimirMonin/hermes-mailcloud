---
applyTo: "**"
name: "AGENT.Kanban"
description: "Hermes Kanban identity and durable task-handling rules for this repository."
---

# AGENT — Kanban

```text
board: hermes-mailcloud
default workdir: repository root of the active repository checkout
```

- Use the `hermes-mailcloud` board for work belonging to this repository.
- Keep card scope and acceptance criteria aligned with the requested repository change.
- Do not copy card IDs, transient progress, activity logs, current test counts, or completion reports into `AGENTS.md`, project instructions, or documentation.
- Do not create repository status/history/report files as a substitute for updating the board.
- Repository edits, Git commits, pushes, and cloud operations remain subject to their own explicit authorization boundaries; a Kanban card alone is not authorization.
- Terra owns bounded implementation slices. Sol/default owns independent stage review, semantic decisions, direct micro-fixes, and accepted scoped commits.
- Card creation has real model/token/time cost. Do not create a card for a one-to-three-line docs/instruction/router/wording/formatting/control-plane correction unless it changes product semantics, schema, privacy, integrity, security, or dependency structure. Sol/default applies such micro-fixes directly and runs only affected deterministic checks.
- Do not use `blocked` for downstream review, routine verification, documentation synchronization, or Mail.ru access already authorized by the owner. A blocker requires a demonstrated unresolved credential, existing-data risk, ambiguous external side effect, frozen-contract conflict, or exhausted safe repair strategy.
- Status reminders are coordination impulses: read live board state, continue the already-approved chain when safe, and avoid duplicate cards or repeated permission questions.
