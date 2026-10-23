---
name: pf-maintain
description: Maintain project knowledge after a bounded change. Update or create documents and owner instructions, preserve history, repair navigation and check metadata without silently changing policy. Use for documentation impact, stale contracts, instruction sync or archival work, not product implementation or a whole-corpus audit.
metadata:
  version: "0.2.0"
  updated: "2026-10-21"
---

# Maintain affected knowledge

## Use / do not use

Use after a behavior/contract/owner change, for a new durable document, or when a
specific stale statement prevents work. Not for redesigning the application,
overwriting local instructions from a fresh template, automatically accepting a
proposal, or improving unrelated documents indefinitely. No mandatory subagents.

## Inputs

Project root and native rules; bounded task/accepted change and verification limits;
existing documentation entry/profile; permitted write paths and relevant dirty work.
Read the project's adapted documentation/instruction-authoring instructions first.
If absent, use the [documentation form](../../templates/instructions/documentation.md.tmpl)
and [instruction-authoring form](../../templates/instructions/instruction-authoring.md.tmpl)
as guidance, not permission to replace local policy.

## Procedure

1. Find the current owner of the affected knowledge. Is it a rule, a map, current
   state, or durable decision history? These are four roles, not four required files;
   state stays in the existing tracker, and one document may cover several roles.
   Distinguish accepted requirement,
   observed implementation, proposed change and actual evidence. Read only relevant
   sources; establish root/freshness before relying on indexed absence.
2. Choose one: update the existing owner, link to it, create a missing distinct
   responsibility, archive/replace obsolete knowledge, or justify no-document-impact.
   Use [lifecycle](../../references/lifecycle.md) and the single
   [metadata schema](../../references/metadata.md). No file per checklist row.
3. Record a finite create/change list before writing; check intersections, preserve
   unknown modifications. For a new instruction bind its trigger to actual owners,
   contracts, invariants and checks using the
   [profiled instruction](../../templates/documents/profiled-instruction.md.tmpl).
4. Write only the affected durable delta. Synchronizing an accepted owner/command is
   not permission to change expenses, access, safety, release rules or independent
   review. Surface such a conflict to the policy owner and continue independent work.
5. Repair nearest entry/catalog and actual client route where in scope. A link is
   not proof of automatic injection. On replacement preserve origin, replacement
   scope, outstanding obligations and historical evidence via the
   [archive frame](../../templates/documents/archive-frame.md.tmpl). For a significant
   intentional removal, keep its rationale, replacement responsibility owner and
   conditions for reconsideration in existing decision history/archive. Do not
   resurrect it by ignoring that reason or create a second deletion ledger.
6. Check filled properties/types/IDs/local links, no unresolved required placeholders,
   current/proposed separation and affected guides/translations. Use the project's
   verified check command; see [quality](../../references/quality.md) for evidence
   limits. Optional [Obsidian views](../../templates/obsidian/README.md) select the
   same Markdown; do not create another wiki or require GUI.
7. Follow the project's review/save policy under
   [lifecycle](../../references/lifecycle.md#владелец-приёмки-и-повторных-проверок);
   do not appoint another review layer or waive required independence.
   Return actual paths, sufficient checks/raw exits, limitations and exact remainder.
   Promote useful temporary conclusions into the knowledge owner, not an entire run log.

## Missing input / stop

Ask one specific question only when an unresolved ownership/policy decision blocks
the affected action. For missing technical facts do one bounded source lookup, not
an annual archive audit. A consumer outside write scope is an exact integration
handoff, not a reason to edit it secretly or claim complete connection. Stop when
the task's affected knowledge is consistent, reachable and checked; reapplication
with no real delta is a no-op. Package upgrades are separate from project adaptations.

## Examples

**Positive:** an accepted CLI option is renamed. Update its existing contract,
owner instruction and affected guide, preserve old-release history, check links
and report unrun runtime checks. Do not create three new summaries of the same rule.

**Incorrect:** rewrite a privacy rule to match a leaking implementation and mark
all plans accepted because the linter is green. That hides a defect/policy decision,
not maintenance.
