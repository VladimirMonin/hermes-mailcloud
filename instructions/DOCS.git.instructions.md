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

- Commit only with explicit user authorization, including a program-level grant to the designated reviewer for accepted local scoped commits. That grant need not be requested again for each accepted slice.
- Push only after an explicit user request to push; permission to commit does not imply permission to push. When the current grant requires accepted-slice delivery, the same accepting reviewer completes affected documentation/instructions, the scoped commit and that push without another permission round. Bind the verified destination and explicit accepted SHA/refspec, disable follow-tags, and read back the exact remote ref; command success alone is not delivery proof.
- Never rewrite history, force-push, discard user changes, or amend an existing commit without explicit direction.
- For owner-approved direct Pi development, one coder writes coherent code/test slices and freezes each candidate. One independent designated reviewer owns the technical verdict, the index, and the already-authorized scoped local commit after PASS. Each worker reports to Hermes; concrete FAIL/findings go to Hermes for rework and priority decisions, not directly into a worker-owned next-stage pipeline. The coder does not stage or commit. Keep the candidate frozen until Hermes dispatches corrections or the reviewer commits the accepted scope.
- Before committing, bind raw accepted files to expected stored blobs, including any explicit EOL conversion; verify actual parent, changed path set and every committed blob afterward. Preserve vendored snapshot bytes with command-local staging settings where needed, not source normalization or persistent configuration changes.
- Before committing, verify that the effective author and committer use the configured public GitHub noreply identity without printing private email values. Do not change global Git configuration or recover old personal identity data.
- Tiny documentation/instruction corrections need no separate Kanban card or worker session. The designated reviewer may apply them directly and rerun only affected deterministic checks; a docs-only bootstrap does not require the full Python suite.
- After an accepted code commit, Hermes dispatches the next top-level code slice; workers do not start it themselves. The reviewer may update documentation/instructions concurrently on explicitly disjoint paths. Keep a single index owner, stage exact paths, and never include the coder's in-flight changes in a documentation commit.
