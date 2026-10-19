# Hermes MailCloud documentation

`README.md` at the repository root is the current project entry point. This directory contains the frozen v0.1 contract, safety guidance, testing strategy, release notes, historical architecture research, and accepted architectural decisions.

> Many command and module descriptions are plans for later waves. Confirm implemented behavior in `src/hermes_mailcloud/` and `tests/`.

## Guide

- [`00-research-summary.md`](00-research-summary.md) — research summary.
- [`01-architecture.md`](01-architecture.md) — target architecture and boundaries.
- [`02-command-contract.md`](02-command-contract.md) — frozen CLI contract, explicit dependency setup, and labeled future proposals.
- [`03-development-plan.md`](03-development-plan.md) — implementation waves.
- [`04-probe-plan.md`](04-probe-plan.md) — implemented safe probe harness and planned live capability evidence.
- [`05-safety-model.md`](05-safety-model.md) — safety model.
- [`06-testing-strategy.md`](06-testing-strategy.md) — offline-first and opt-in live testing.
- [`07-agent-integration.md`](07-agent-integration.md) — agent invocation, JSON/error handling, safety rules, and labeled future proposals.
- [`08-configuration-and-secrets.md`](08-configuration-and-secrets.md) — configuration and secret boundaries.
- [`09-known-risks.md`](09-known-risks.md) — known risks.
- [`10-v0.1-release-notes.md`](10-v0.1-release-notes.md) — 0.1.0a1 alpha features, limits, package and CI release gates.
- [`11-local-installation.md`](11-local-installation.md) — non-editable `uv tool` / release-wheel installation, student setup, local configuration, and optional Hermes skill.
- [`../skills/mailru-cloud/SKILL.md`](../skills/mailru-cloud/SKILL.md) — compact agent router for Mail.ru Cloud requests.
- [`adr/`](adr/) — architectural decision records.
- [`agent-workflow.md`](agent-workflow.md) — durable agent-instruction maintenance.

Do not add status, history, session-report, progress-report, or current-run evidence pages to this documentation set.
