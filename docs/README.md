# Hermes MailCloud documentation

`README.md` at the repository root is the current project entry point. This directory contains the frozen v0.1 contract, safety guidance, testing strategy, release notes, historical architecture research, and accepted architectural decisions.

> Many command and module descriptions are plans for later waves. Confirm implemented behavior in `src/hermes_mailcloud/` and `tests/`.

## Guide

- [`foundation/project-philosophy.md`](foundation/project-philosophy.md) — purpose, engineering priorities and finite completion.
- [`foundation/architecture-principles.md`](foundation/architecture-principles.md) — command-first direction, application ownership and compatibility boundaries.
- [`plans/command-first-refactor.md`](plans/command-first-refactor.md) — proposed command-first roadmap, remaining migration and acceptance criteria; current implemented methods are documented in the architecture.
- [`foundation/observability-policy.md`](foundation/observability-policy.md) — useful diagnostics, privacy, actual channels and external-transfer limits.
- [`../tools/project-foundation/README.md`](../tools/project-foundation/README.md) — complete imported methodology, skills and source attribution; not current product behavior.

- [`00-research-summary.md`](00-research-summary.md) — research summary.
- [`01-architecture.md`](01-architecture.md#current-in-process-application-interface) — current fifteen-method Application API, shared CLI ownership, setup/doctor/batch semantics and remaining private-glue cleanup; historical proposals are labeled separately.
- [`02-command-contract.md`](02-command-contract.md) — frozen CLI contract, explicit dependency setup, and labeled future proposals.
- [`03-development-plan.md`](03-development-plan.md) — implementation waves.
- [`04-probe-plan.md`](04-probe-plan.md) — implemented safe probe harness and planned live capability evidence.
- [`05-safety-model.md`](05-safety-model.md) — safety model.
- [`06-testing-strategy.md`](06-testing-strategy.md) — offline-first and opt-in live testing.
- [`07-agent-integration.md`](07-agent-integration.md) — CLI and supported in-process agent invocation, JSON/error handling, safety rules, and labeled future proposals.
- [`08-configuration-and-secrets.md`](08-configuration-and-secrets.md) — configuration and secret boundaries.
- [`09-known-risks.md`](09-known-risks.md) — known risks.
- [`10-v0.1-release-notes.md`](10-v0.1-release-notes.md) — stable 0.1.0 functionality, retained alpha verification boundaries, limits and release gates.
- [`11-local-installation.md`](11-local-installation.md) — installing uv, recommended/nonmandatory uv tool, pinned stable wheel, saved-connection selection, refresh and optional skill.
- [`../skills/mailru-cloud/SKILL.md`](../skills/mailru-cloud/SKILL.md) — compact agent router for Mail.ru Cloud requests.
- [`adr/`](adr/) — architectural decision records.
- [`agent-workflow.md`](agent-workflow.md) — durable agent-instruction maintenance.

Do not add status, history, session-report, progress-report, or current-run evidence pages to this documentation set.
