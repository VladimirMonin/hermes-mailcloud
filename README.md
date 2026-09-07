# Hermes MailCloud

Unofficial, rclone-backed, JSON-first CLI for Mail.ru Cloud.

> Status: **0.1.0a0 alpha** — `version`, `doctor`, `ls`, `stat`,
> `mkdir`, `upload`, `download`, `mv`, `cp`, guarded `rm`, `publish`, `link`,
> and `batch` are implemented through the typed rclone boundary. `publish`/`link`
> require an owner-private local link journal and return only a public-link
> fingerprint. `batch` validates a strict versioned JSON plan, supports zero-call
> dry-runs, and reports ordered partial failures. `doctor` defaults to read-only
> rclone/config/remote checks; generated `/TEST` probes require `--live --yes`.
> `unlink`, direct-download resolution, link expiry/passwords, and a full link
> audit are not shipped in v0.1.

This independent project is not affiliated with, endorsed by, sponsored by, or
otherwise associated with Mail.ru or VK. “Mail.ru” and “Облако Mail.ru” are
trademarks of their respective owners and are used only to identify the service
with which this CLI is intended to interoperate.

## Current publication state

This working tree is a **private, unpublished** `0.1.0a0` candidate. It does
not claim that a public repository, immutable `v0.1.0a0` tag, GitHub Release,
or PyPI distribution exists. Public visibility and release require separate
owner approval. Before any PyPI upload, the protected GitHub `pypi` environment
with its required reviewer and the matching Trusted Publisher must also be
configured and read back; those are external prerequisites, not repository-byte
claims.

## Future installation routes

The routes below become usable only after the owner has approved public
visibility and created the annotated, never-moved `v0.1.0a0` tag from the
accepted release commit. The PyPI route additionally requires the protected
`pypi` environment, configured Trusted Publisher, and completed PyPI upload.

### PyPI route

After that PyPI upload, install the exact tested alpha release:

```bash
uv tool install --python 3.12 "hermes-mailcloud==0.1.0a0"
hermes-mailcloud version
hermes-mailcloud --json doctor
```

The exact project pin selects `hermes-mailcloud` 0.1.0a0; it does not pin every
transitive dependency for a future resolver. Change the pin only after accepting
a later release, then reinstall deliberately with `--force`.

### Immutable source route

Only after the public repository and the immutable tag exist, maintainers who
need source provenance can install that release tag instead of a moving
checkout:

```bash
uv tool install --python 3.12 \
  "git+https://github.com/VladimirMonin/hermes-mailcloud.git@v0.1.0a0"
```

Use an accepted tag or full commit ID, never a moving branch name, for an
operational command. Until those publication conditions are met, use a checkout
only for development or smoke testing. See the full
[installation and update policy](docs/11-local-installation.md).

## Development route

```bash
uv sync --locked --all-groups --all-extras
uv run hermes-mailcloud --help
uv run hermes-mailcloud version
uv run pytest -q -m "not live"
uv run ruff check .
```

Use `uv run` only for development and smoke testing. A bare `.` install is a
development convenience, not an operational provenance route.

Mail.ru credentials remain in the user's private `rclone` configuration. The
complete student setup, local config, immutable skill install, and update policy
are in [`docs/11-local-installation.md`](docs/11-local-installation.md).

## Package smoke test

Build and install the wheel into a fresh virtual environment. This smoke test
does not use a Mail.ru credential or run a live probe; `doctor --json` remains
read-only.

```bash
uv build
smoke_dir="$(mktemp -d)"
uv venv "$smoke_dir/venv" --python 3.12
uv pip install --python "$smoke_dir/venv/bin/python" dist/*.whl
smoke_env=(env -i PATH="$PATH" HOME="$smoke_dir/home" XDG_CONFIG_HOME="$smoke_dir/config")
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" --help
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" version
"${smoke_env[@]}" "$smoke_dir/venv/bin/hermes-mailcloud" --json doctor
rm -rf "$smoke_dir"
```

GitHub Actions runs the same lock, lint, format, offline-test, build, metadata,
license-payload, constrained-runtime-graph, and clean wheel-and-sdist smoke
gates without Mail.ru credentials or live tests.

## Live tests (require real rclone + Mail.ru remote)

```bash
HMC_LIVE=1 HMC_REMOTE=mailru: uv run pytest -q -m live
```

The live file suite creates and removes only one fresh `/TEST/hermes-mailcloud-*`
root (or a validated `HMC_TEST_ROOT` override); it never uses existing cloud data.
`hermes-mailcloud doctor --json` is read-only. `doctor --json --live --yes` is a
separate opt-in diagnostic that uses fresh generated `/TEST/hermes-mailcloud-*`
roots and leaves existing cloud data metadata/list-only.

## Architecture

```
Hermes Agent → hermes-mailcloud CLI → policy + JSON contract → rclone subprocess → Mail.ru Cloud
```

See `docs/01-architecture.md` and `docs/03-development-plan.md` for the full plan.

## Release, licensing, and support boundaries

- [Release notes and publication policy](docs/10-v0.1-release-notes.md)
- [Local installation and student setup](docs/11-local-installation.md)
- [MIT project license](LICENSE)
- [Third-party notices and runtime ledger](THIRD_PARTY_NOTICES.md)
- **Project CLI, documentation, or packaging defects:** after public visibility,
  use the project's [GitHub Issues](https://github.com/VladimirMonin/hermes-mailcloud/issues)
  with the command version, exit code, and redacted diagnostics. Before then,
  that public issue route is unavailable; use only an owner-approved private
  channel.
- **rclone backend or configuration defects:** use the upstream
  [rclone documentation and support](https://rclone.org/docs/), not this
  project's issue tracker.
- **Mail.ru account, service, quota, or access problems:** use official Mail.ru
  support, not this CLI's project tracker.

Never include rclone configuration, passwords, access tokens, cloud object
names, or raw public links in any support request. Share only redacted
diagnostics and public-link fingerprints through an appropriate approved route.