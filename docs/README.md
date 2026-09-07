# Hermes MailCloud documentation

`README.md` at the repository root is the current project entry point. This directory contains the frozen v0.1 contract, safety guidance, testing strategy, release notes, historical architecture research, and accepted architectural decisions.

> Many command and module descriptions are plans for later waves. Confirm implemented behavior in `src/hermes_mailcloud/` and `tests/`.

## Guide

- [`00-research-summary.md`](00-research-summary.md) — research summary.
- [`01-architecture.md`](01-architecture.md) — target architecture and boundaries.
- [`02-command-contract.md`](02-command-contract.md) — proposed CLI contract.
- [`03-development-plan.md`](03-development-plan.md) — implementation waves.
- [`04-probe-plan.md`](04-probe-plan.md) — implemented safe probe harness and planned live capability evidence.
- [`05-safety-model.md`](05-safety-model.md) — safety model.
- [`06-testing-strategy.md`](06-testing-strategy.md) — offline-first and opt-in live testing.
- [`07-agent-integration.md`](07-agent-integration.md) — proposed agent-facing behavior.
- [`08-configuration-and-secrets.md`](08-configuration-and-secrets.md) — configuration and secret boundaries.
- [`09-known-risks.md`](09-known-risks.md) — known risks.
- [`10-v0.1-release-notes.md`](10-v0.1-release-notes.md) — current private-candidate status and future owner-gated package, tag, artifact, GitHub Release, PyPI, Trusted Publishing, and CI gates.
- [`11-local-installation.md`](11-local-installation.md) — future-conditional PyPI/source/skill routes plus local development, configuration, and update policy.
- [`../LICENSE`](../LICENSE) — project MIT license carried by the distribution.
- [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) — third-party notices, license sources, and the exact locked runtime ledger.
- [`../skills/mailru-cloud/SKILL.md`](../skills/mailru-cloud/SKILL.md) — compact agent router for Mail.ru Cloud requests.
- [`adr/`](adr/) — architectural decision records.
- [`agent-workflow.md`](agent-workflow.md) — durable agent-instruction maintenance.

Do not add status, history, session-report, progress-report, or current-run evidence pages to this documentation set.
