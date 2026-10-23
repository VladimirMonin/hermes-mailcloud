# Metadata and authoring contract — Kit 0.2.0

This is the single shared schema for **adapted durable project documents**, not a
runtime configuration or a schema for every Markdown file. Project-native formats
win. Apply it to newly authored documents and deliberate migrations; do not stamp
an old corpus en masse. A template is an unfilled source; an adapted document is
project-owned knowledge. The package itself remains a separate versioned resource.

## Required initial YAML

| Key | Type | Meaning |
|---|---|---|
| `id` | Non-empty string | Stable unique identity in the selected project corpus; keep on a move |
| `title` | Non-empty string | Human-readable subject |
| `kind` | String from vocabulary below | Role of this document, not readiness of a feature |
| `status` | String from five values below | Acceptance/lifecycle of the text |
| `created` | Quoted ISO `YYYY-MM-DD` string | Creation of this document |
| `updated` | Quoted ISO `YYYY-MM-DD` string | Actual editorial revision, not evidence freshness |
| `areas` | Non-empty list of non-empty strings | Responsibilities/topics |
| `summary` | Non-empty string | Useful question/answer and scope, not a session narrative |

Keep strings strings: quote dates, versions, revision numbers and ambiguous values.
No duplicate keys or IDs, executable YAML tags, anchors or merge keys. Use a safe
YAML parser with duplicate-key rejection. Missing knowledge is explicit in prose,
not a fabricated date or command. For imported history whose original creation is
unknown, preserve it unchanged behind a newly dated archival frame; do not invent
the original date. `null` is **not** valid for required fields in this Kit schema.

### `kind` vocabulary

| Values | Responsibility |
|---|---|
| `philosophy`, `engineering_policy` | Reasons/trade-offs; shared engineering rules |
| `instruction` | Triggered practical procedure with owner, constraints and checks |
| `architecture`, `contract`, `reference` | Current structure; behavioral boundary; precise lookup |
| `scenario` | User, goal, normal/error paths and observable outcome |
| `proposal`, `plan`, `decision` | Option under consideration; executable slices; reasoned choice |
| `research`, `incident` | Bounded question/experiment; defect investigation |
| `guide` | User task, setup, reference or troubleshooting |
| `verification` | What actually ran, on what, result and limits |
| `journal`, `handoff` | Significant history; next bounded action |
| `snapshot`, `template`, `navigation` | Preserved edition; inert form; reader routes |

Release notes use `journal`, a glossary uses `reference`; do not create synonymous
kinds. A project may deliberately extend the vocabulary with one owner and update
its checker/views. An unrecognized kind is not silently accepted or coerced.

### `status` vocabulary

- `draft`: unfinished text, assumptions/questions remain visible.
- `proposed`: coherent candidate for a decision/review, not permission to implement.
- `accepted`: accepted **for the stated purpose and scope**; cite the decision in
  context. An accepted plan is not an implemented capability; an accepted report
  may honestly record a failed test.
- `superseded`: replaced by named knowledge with explicit replacement scope.
- `archived`: withdrawn from active use, with reason; not permission to erase data.

Do not put PASS, DONE, implemented, current or needs-review in `status`. Requirement,
observed implementation, proposal, historical fact and executed verification are
different assertions. Changing a date cannot upgrade any of them.

## Optional fields: fixed types, purpose first

| Key | Type | Use |
|---|---|---|
| `related` | List of document-ID strings | Meaningful relations; also supply human Markdown links |
| `issue_refs` | List of strings | Stable tracker references, not a duplicate task status |
| `owner`, `release_owner` | Non-empty strings | Responsible project role/person; release accountability when applicable, not agent model/session |
| `read_when` | Non-empty string | Required by convention for `instruction`; concrete task/files/contracts trigger |
| `version` | Non-empty string | Edition of this text, not implicitly application version |
| `code_ref` | Non-empty string | Exact source revision actually inspected |
| `code_verified_at` | Quoted ISO date string or YAML `null` | Date of substantive source comparison; null means not established |
| `verification_scope`, `review_note` | Non-empty strings | What was checked; specific uncertainty/drift |
| `evidence_refs` | List of strings | Accessible evidence links with context, not assumed public artifacts |
| `supersedes` | List of document-ID strings | New document declares replacement, whole or bounded in prose |
| `snapshot_of` | One document-ID string | Origin of an independently identified preserved edition |
| `language` | Non-empty string | Language/locale, e.g. `ru`, `en`, `pt-BR`; not content recognition language |
| `source_revision` | Non-empty string | Primary guide's content edition, e.g. `r2` |
| `translation_source` | One document-ID string | Primary guide ID, never a path or list |
| `translation_source_revision` | Non-empty string | Actual primary edition checked by the translator |
| `translation_state` | `current`, `outdated` or `unknown` string | Translation review summary; see reconciliation below |

Omit irrelevant optional keys instead of empty strings or dozens of N/A. New fields
need a concrete consumer, documented type and one owner. Preserve native loader
fields where used rather than replacing them with similar authoring keys.

## Guides and translation reconciliation

The project profile chooses its primary guide language and required release
translations. Do not infer language from directory alone. Every language file has
its own `id` and `language`; pairs use `related` and reciprocal ordinary relative
Markdown links. The primary has `source_revision`; a translation has
`translation_source`, `translation_source_revision`, and `translation_state`.
Do not give a translation a second independent `source_revision` in this model:
translate directly from the named primary, not a chain of translations.

Reconcile whenever primary content changes, before claiming readiness, and before
the relevant release:

1. Resolve `translation_source` by unique ID within the selected permitted corpus.
   Missing source/revision or inaccessible source means **unknown**, not current.
2. Unequal revision strings mean **outdated**, even if dates match. Equal revision
   strings mean eligible for **current** only after a substantive translation review
   of steps, restrictions, examples and locale/version images.
3. `translation_state` is a human review summary, not a second authority overriding
   revision comparison. It may remain unknown/outdated conservatively. Marking
   current with unequal revisions is an error. Never bump the checked revision
   without doing the review. A checker can detect contradictions, not translation quality.
4. A content change increments the primary edition, e.g. `r1` to `r2`; its author
   updates linked translation states in the same logical slice, or names an exact
   out-of-scope repair to the owner. Deferred translations keep the old checked
   edition and a visible warning/link to the primary. Pure formatting can have
   a justified no-translation-impact result without artificial revision churn.

The feature/guide author updates affected knowledge; the guide owner maintains the
pair/glossary; the release owner assigns actual translation work and ensures required
languages are reconciled before that release. The reviewer checks consistency.
A deferred language is not declared ready. `updated` equality never proves parity.

## Templates, native files and navigation

`.md.tmpl` files are agent authoring resources. Copy **only the marked payload**,
fill `{{field_name}}`, remove irrelevant sections, and recalculate relative links
from the output location. Agent placeholders are not arbitrary variables supported
by Obsidian's core Templates plugin. Required unresolved fields must be resolved
before handoff, or replace the claim with explicit draft uncertainty; do not leave
unfilled tokens in a supposedly finished project document.

Native `SKILL.md` uses Agent Skills `name`/`description` and optional string-valued
`metadata`. Native `AGENTS.md`, profile YAML, `.base`, runtime prompts, external and
immutable evidence retain their own grammar; do not force this passport on them.
A wrapper can catalogue an immutable item without modifying the item.

Default new-project destinations: `docs/foundation/`, `instructions/`, `architecture/`,
`scenarios/`, `decisions/`, `plans/`, `research/`, `guides/<language>/`, `views/`,
`assets/`, `_templates/`, `archive/`. These are relative to the existing `docs/`
root, not a requirement to create every empty folder or migrate a working tree.
Temporary reports remain in the task's authorized temporary area, not active knowledge.
Keep one Markdown source; a catalog/Bases view is a selection of it, not a separate DB.
See [lifecycle](lifecycle.md) and [Obsidian setup/selection](../templates/obsidian/README.md).
