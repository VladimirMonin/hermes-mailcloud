---
applyTo: "tests/**/*.py,src/**/*.py,pyproject.toml,uv.lock"
name: "TEST.QualityGates"
description: "Offline-first test, lint, format, and opt-in live-test rules."
---

# TEST — Quality gates

## Choose meaningful evidence

- The strategy owner is [docs/06-testing-strategy.md](../docs/06-testing-strategy.md); diagnostics follow [LOG.observability.instructions.md](LOG.observability.instructions.md). These rules adapt Project Foundation Kit testing/quality procedures without replacing the project's test harness.
- Before writing a test, name the user-visible success, important refusal, real application owner, consumer, and preserved invariant. Exercise real application wiring; replace only the external/expensive/nondeterministic boundary. Do not implement the expected product behavior a second time in a fake.
- Before imports or pytest collection, inspect bootstrap/plugins and establish disposable configuration, home, journal, backend and temporary roots. `tmp_path` inside a test does not protect earlier configuration access. Use the synthetic environment recipe in `.github/workflows/ci.yml`; never read the user's credentials to construct a fixture. Register cleanup immediately after acquisition, including partial setup.
- For a new application boundary, verify both direct API calls without the CLI framework and CLI → actual application owner → actual result. Assert observable results and resource readback where applicable, not only mock call counts. Preserve argument errors, exit codes, dry-run zero-backend behavior, write-once retry policy, partial batch results and publication safeguards. Installed import-independence checks must block CLI SDK imports before the first product import; run full CLI provenance in a separate process, not before the API check.
- For a regression, retain the first failing observation; distinguish a product defect from an invalid fixture, observer or environment. Do not weaken an assertion to fit the implementation. Recheck affected cases when fixtures, serialization, configuration or artifacts change.
- Record actual command/selection, raw exit, environment/artifact boundary, substituted dependencies, skips and limitations in the authorized private handoff. Written, executed, skipped, cancelled, blocked and independently accepted are different facts. A skipped required case is not PASS; old platform evidence is not fresh qualification.
- Full offline execution is required for a cross-cutting application refactor; a documentation-only change needs semantic/link/whitespace checks, not the runtime suite. Test count and coverage alone do not establish correctness.

## Execute the applicable gates

- Start with the smallest test that exercises the changed behavior, then run the offline suite.
- Ordinary checks must not require network access, a Mail.ru account, rclone credentials, or a configured remote.
- Keep tests deterministic; fake external subprocess/cloud behavior rather than using live services in unit or ordinary integration tests.
- Mark real cloud tests with `live`. Without explicit live intent, run:

```bash
uv run pytest -q -m "not live"
```

- Run live tests only under an existing explicit owner grant and with suitable isolated credentials. The canonical remote test root is `/TEST/<unique-run-id>/`; do not ask again for each card while the same bounded grant remains active. Never print credential values or raw public URLs.
- Before mutation, prove the normalized target is a descendant of `/TEST/`. After each test, verify that only same-run objects were removed and that existing objects outside `/TEST` were unchanged.
- Public-link checks may use bounded HTTP or browser tooling against the generated test URL. Keep the URL owner-private, allowlist the expected Mail.ru host/path, limit redirects/time/body size, and record only a redacted fingerprint plus status/classification.
- For Python changes, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live"
```

- For dependency changes, also run `uv lock --check`.
- Always finish repository edits with `git diff --check`.
