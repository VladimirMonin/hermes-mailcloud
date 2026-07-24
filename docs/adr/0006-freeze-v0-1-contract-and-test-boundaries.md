# ADR 0006. Freeze v0.1 contract and test boundaries

> Status: accepted
> Date: 2026-07-24
> Project: `hermes-mailcloud`

## Context

The initial research and draft command documents described a wider capability
set than a safe first release. In particular they mixed proposed `sync`,
`resolve`, private-API fallbacks and public-link options with the current
external-rclone design. They also described mutable doctor/probe roots outside
the project test boundary.

## Decision

The v0.1 public command set is exactly:

```text
doctor ls stat mkdir upload download mv cp rm publish link batch
```

`auth` is not a command. Credentials remain with rclone and `doctor` reports
readiness without emitting credentials.

`unlink` is conditional and absent from v0.1 until one bounded live run proves
both `rclone link --unlink` and invalidation of the generated public URL.
`sync`, `resolve`, direct-download resolution, private API, expiration/password
links and a full links audit are post-v0.1.

`publish` and executing a batch containing a write require `--yes`.
`publish` and `link` accept only normalized descendants of the fixed
`/Hermes/public` root. v0.1 has neither `--allow-outside-public-root` nor an
`--allow-dangerous-file` escape hatch.

`doctor` defaults to `read_only`; mutating checks require explicit `--live`.
Every project-owned live mutation, including live doctor/probe work, is confined
to a generated `/TEST/<unique-run-id>/` descendant. Existing objects outside
`/TEST` are metadata/list-only.

The result envelope contains exactly one of `result` and `error`. A partial
batch exits `11` and puts per-operation outcomes at `result.items`; it has no
top-level `error`. Write retries are opt-in only after an operation-specific
idempotency decision; ambiguous write side effects are not retried.

A local journal is owner-private capability data. Raw provider output is never
persisted there; public URLs and probe artifacts are never committed or copied
to Kanban/chat, and all shared diagnostics use redaction/fingerprints.

## Consequences

- `schemas/` and schema tests define the stable machine contract before behavior
  code lands.
- ADR 0004's historical escape-hatch proposal is superseded for v0.1.
- Later capability work must add its own verified contract and tests rather
  than expanding this release implicitly.
