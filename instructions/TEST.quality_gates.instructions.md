---
applyTo: "tests/**/*.py,src/**/*.py,pyproject.toml,uv.lock"
name: "TEST.QualityGates"
description: "Offline-first test, lint, format, and opt-in live-test rules."
---

# TEST — Quality gates

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
