---
applyTo: ".gitignore,AGENTS.md,instructions/**/*.instructions.md,docs/**/*.md,README.md,pyproject.toml,uv.lock,src/**,tests/**,schemas/**"
name: "DOCS.Git"
description: "Git staging, conventional commit message, secret/artifact, commit, and push contract."
---

# DOCS — Git contract

## Before staging or committing

- Inspect Git status, unstaged changes, untracked files, and the staged diff separately.
- Stage only files in the requested scope. Never stage `.env`, credentials, rclone configuration, cloud payloads, `links.jsonl`, databases, logs, caches, build output, generated probe artifacts, or editor/OS state.
- Run the smallest relevant quality gates and `git diff --check` before proposing a commit.

## Commit messages

- Derive the message only from the staged diff (`git diff --cached`). Do not describe unstaged work or planned follow-up.
- Use a concise conventional prefix appropriate to the staged change: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `ci:`, or `chore:`.
- Describe intent, not an activity log. Do not include prompts, raw command output, test logs, card history, or generated reports.
- If the staged diff contains unrelated concerns, split it instead of inventing a broad message.

## Authorization boundary

- Commit only after an explicit user request to commit.
- Push only after an explicit user request to push; permission to commit does not imply permission to push.
- Never rewrite history, force-push, discard user changes, or amend an existing commit without explicit direction.
- For an owner-approved staged program, Terra writes the bounded stage, Sol/default independently reviews it, and Sol/default creates the scoped commit only after an exact PASS. Implementation and review workers do not commit.
- Tiny accepted documentation/instruction corrections do not require a separate Kanban card or worker session; Sol/default may apply them directly before the scoped commit and rerun only the affected deterministic checks.
