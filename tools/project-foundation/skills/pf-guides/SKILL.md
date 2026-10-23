---
name: pf-guides
description: Create or update user guides from real scenarios and implemented interfaces. Cover getting started, task steps, reference and troubleshooting; maintain primary-language guides, RU/EN translations and revision lag. Use for user-visible changes or release guide readiness, not invented capabilities or automatic translation of all internal docs.
metadata:
  version: "0.2.0"
  updated: "2026-10-21"
---

# Guide a real user task

## Use / do not use

Use for a changed user journey, command, screen, prerequisite or supported limitation,
including release translations. Do not generate guides from a proposed mockup as if
it shipped, translate the whole engineering corpus, or require Figma/image generation
to finish a useful text guide. This skill neither runs product operations nor publishes.

A future interface needs [pf-ui-design](../pf-ui-design/SKILL.md), not a guide
claiming it shipped. Route there only for a design need; describe the implemented
journey here, without automatically adding another skill/agent to the task.

## Inputs

Project rules/profile and guide owner; selected user/scenario; real interface/version
and evidence; current guide/translation links; primary language and required release
languages. Read the project's guide instruction or adapt the
[guide instruction form](../../templates/instructions/guides.md.tmpl).

## Procedure

1. Locate the existing guide before creating another. Obtain facts from the scenario,
   accepted contract, actual interface and scoped evidence, not feature names or a
   plan. Mark unsupported/deferred modes; distinguish source inspection from observed
   installed behavior. Missing proof never becomes a guaranteed user step.
2. Choose the smallest useful output: getting-started section, task how-to, reference
   or troubleshooting in an existing guide; a new document only for a distinct user
   task. Use the [user-guide form](../../templates/guides/user-guide.md.tmpl) and
   [metadata](../../references/metadata.md), not an agent's execution report.
3. Write result, prerequisites/platform/version, exact actions, observable success,
   significant failure and safe next action. Keep commands, keys, IDs, units and API
   names technically unchanged. Link precise reference data instead of maintaining
   a second independently edited parameter list.
4. Use the project's chosen primary language. For RU/EN or other required translations
   give each file a unique ID, reciprocal ordinary Markdown links and source revision
   metadata. Compare actual revisions, review semantic delta, then update the checked
   edition/state. Dates are not parity proof. Maintain one
   [glossary](../../templates/guides/glossary.md.tmpl) or reuse an adequate existing one.
5. Review screenshots only when needed and authorized: actual implementation,
   safe content, correct language/version or explicit explanation, alt/caption and
   provenance. A concept is clearly future design, never implementation evidence.
   Preserve original evidence; do not take private screenshots just to decorate text.
6. The feature/guide author updates affected source and translations. Guide owner
   owns ongoing pair/glossary care; release owner assigns actual work and confirms
   required languages before the corresponding release. Deferred translation keeps
   old checked revision plus visible warning/current-source link, never fake freshness.
7. Check source-to-step fidelity, supported failure path, both language links, unique
   IDs, revision/state consistency, examples and image labels. Run the project's
   verified documentation check; report raw results and unrun product/visual checks.
   Add the nearest guide entry and follow the project's acceptance policy in
   [lifecycle](../../references/lifecycle.md#владелец-приёмки-и-повторных-проверок),
   without inventing another reviewer or waiving required review.

## Missing input / finish

Ask for primary language, release scope or unsupported product promise if it cannot
be established from project sources; do not invent these by directory name. A narrow
source lookup can resolve an interface fact. Stop when the selected task is usable,
its limitations are honest and required language impact is resolved or explicitly
assigned. Do not publish a required stale translation as release-ready.

## Examples

**Positive:** a real import command changes its flag. Update the primary how-to and
linked EN version against primary edition r3, preserve the literal flag, and show
how the user recognizes success or an unsupported format. Same dates alone do not
close the translation work.

**Incorrect:** turn a future dashboard concept into a screenshot-led manual, claim
all languages current and block delivery until a new image model is installed.
