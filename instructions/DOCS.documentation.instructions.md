---
applyTo: "README.md,docs/**/*.md,AGENTS.md,instructions/**/*.instructions.md"
name: "DOCS.Documentation"
description: "Documentation, ADR, AGENTS router, and durable instruction governance."
---

# DOCS — Documentation governance

- `README.md` is the concise current entry point; `docs/README.md` indexes detailed documentation.
- Verify statements against current source, tests, manifests, schemas, and accepted ADRs. Clearly label planned or unimplemented behavior.
- Update user-facing documentation when setup, CLI, configuration, schema, safety, or test behavior changes.
- Use an ADR for a durable architectural decision or reversal; do not rewrite accepted decision history to hide a change.
- Keep `AGENTS.md` a small router. Put durable atomic rules in matching `instructions/*.instructions.md` files with frontmatter containing `applyTo`, `name`, and `description`.
- Add a subsystem instruction only after a stable boundary is confirmed in current code and tests. Do not encode speculative plans as mandatory behavior.
- Do not create status, history, session-report, progress-report, or current-run evidence documents.
- Keep task IDs, temporary findings, test counts, implementation chronology, and personal notes out of durable instructions.
- When instruction routing changes, synchronize `AGENTS.md`, `docs/README.md`, and `docs/agent-workflow.md` as needed.
