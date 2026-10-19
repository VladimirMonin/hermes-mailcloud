# Hermes MailCloud

Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.

> Status: **0.1.0a1 alpha / prerelease package** — `version`, `doctor`, `ls`, `stat`,
> `mkdir`, `upload`, `download`, `mv`, `cp`, guarded `rm`, `publish`, `link`,
> and `batch` are implemented through the typed rclone boundary. Explicit `setup`
> prepares the external rclone dependency for the current user. `publish`/`link`
> require an owner-private local link journal and return only a public-link
> fingerprint. `batch` validates a strict versioned JSON plan, supports zero-call
> dry-runs, and reports ordered partial failures. `doctor` defaults to read-only
> rclone/config/remote checks; generated `/TEST` probes require `--live --yes`.
> `unlink`, direct-download resolution, link expiry/passwords, and a full link
> audit are not shipped in v0.1.
> Full documentation: `docs/`

## Version and platform support

The current package is **0.1.0a1**, an alpha, not a stable release. GitHub
prerelease artifacts use the immutable `v0.1.0a1` tag; see the
[release notes](docs/10-v0.1-release-notes.md) and
[artifact installation](docs/11-local-installation.md#install-from-a-release-wheel).
The `v0.1.0a0` tag remains a historical alpha source snapshot. A tag alone is not
a GitHub Release, a PyPI upload, or a claim of production readiness.
Current sources include POSIX and native
Windows journal and subprocess backends. Local full offline, clean-wheel, real-launcher and
fake-backed runtime checks cover Windows/Linux with Python 3.12 and 3.13. The
Windows checks used elevated processes, not ordinary-user qualification.
Explicit installed setup, managed discovery and real rclone local-file operations
are checked on those targets; default official HTTPS acquisition is checked on
both OSes. Genuine ordinary-user Windows qualification remains incomplete;
elevated checks do not establish an Administrator requirement. Remote GitHub
Actions results must be checked for the specific commit. Local/fake-backed
checks do not prove Mail.ru access. See the [Windows boundaries and limits](docs/11-local-installation.md#windows-configuration).

## Quick start (development)

```bash
uv sync --locked --all-groups --all-extras
uv run hermes-mailcloud --help
uv run hermes-mailcloud version
uv run pytest -q -m "not live"
uv run ruff check .
```

## Install for daily use

Install a non-editable operational command from an accepted alpha repository
revision (non-editable does not mean stable-release quality):

```bash
uv tool install --python 3.12 .
hermes-mailcloud --json setup
hermes-mailcloud version
hermes-mailcloud --json doctor
```

The agent runs `setup` explicitly after installing the Python package; users do
not need to find an executable or edit `PATH`. When needed, it downloads pinned
official rclone for Windows/Linux amd64 over HTTPS, verifies archive/executable hashes,
and activates a private per-user copy outside site-packages. No binary is bundled
in the wheel, no global installation or cloud configuration is performed, and
help/version/doctor/ordinary commands never download implicitly. Existing explicit
executable overrides and a working external rclone remain authoritative.

For the pinned version, offline `--archive`, storage and qualification limits,
see [Prepare rclone](docs/11-local-installation.md#prepare-rclone). Mail.ru
credentials remain in the user's private rclone configuration. The complete
student setup, local config, skill installation, and update procedure
are in [`docs/11-local-installation.md`](docs/11-local-installation.md).

## Package smoke test

After the development sync, build wheel and sdist and run the portable harness
with the selected development interpreter. It creates a new runtime and cwd
outside the checkout, installs only locked runtime dependencies and the wheel,
checks import provenance, then exercises the real launcher without injection and
fake-backed file/public/batch scenarios with installed components. No Mail.ru
credentials or live probe are used; `doctor --json` remains read-only. Missing
build/runtime dependencies may be resolved through package indexes.

```console
uv build --out-dir dist
uv export --locked --no-dev --no-emit-project --no-hashes --no-header --no-annotate --output-file dist/runtime-constraints.txt
uv run --no-sync --offline python scripts/smoke_installed.py --dist-dir dist --constraints dist/runtime-constraints.txt --cache-dir dist/uv-cache --receipt dist/installed-smoke.json
```

Use fresh output/receipt paths for another run: the harness requires exactly one
wheel and sdist and refuses to overwrite an existing receipt. Its temporary
runtime must be outside the checkout; Windows journal scenarios require the
[local NTFS/private-directory boundary](docs/08-configuration-and-secrets.md#windows-journal-boundary).
The script's optional `--offline` flag additionally forbids dependency downloads
and needs a prepared cache; `uv run --offline` alone does not set that flag.

GitHub Actions is configured for Ubuntu/Windows × Python 3.12/3.13, with disjoint
offline packs, build and clean installed smoke per runtime cell, and a separate
lock/lint/format job. Local checks do not establish remote Actions GREEN or a
release qualification.

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

## Repository privacy

Use the GitHub-provided noreply address from your account's email settings for
both author and committer identities. Configure it for this repository before
creating commits or annotated tags; changing Git's display with `.mailmap` does
not remove an address from existing commit objects.

Keep credentials, real cloud data, capability URLs, and machine-specific home
paths out of tracked files and commit or tag messages. Review metadata as well
as file content before publishing; a clean secret scan is not a complete
personal-data check.

After a maintainer announces a privacy-related history rewrite, use a fresh
clone. Preserve and inspect any uncommitted work separately before moving it;
do not merge or push old branches back into the cleaned history. Rewriting
repository history cannot erase existing external clones or guarantee removal
of cached commit views.