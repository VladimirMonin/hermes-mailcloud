# Optional Obsidian views — one Markdown source

These are small native YAML `.base` configurations, not a database, plugin,
DataviewJS app or a Bases interpreter. Ordinary Markdown entry pages and links
remain the normal interface; Obsidian is not required to author or read knowledge.
The [metadata reference](../../references/metadata.md) owns field types and meanings.

## Placement and adaptation

For a **new** project the assumed vault root is its existing `docs/`, not the whole
repository. Copy only the needed `.base` files to `docs/views/`. Paths in their
`file.inFolder()` filters are **vault-relative**, not relative to the `.base` file.
`Documents.base`, `Scenarios.base`, `Guides.base` are editable project adaptations;
package upgrades do not overwrite them or local layout decisions. Keep one copy
of project documents, no nested wiki repository or synchronized second knowledge DB.

Existing projects retain their structure. Before using a view, change its folder
predicates to the actual documented knowledge roots and preserve exclusions. For a
repository-root vault you must prefix the documentation paths (e.g. `docs/scenarios`)
and restrict the root-navigation predicate; do not let `file.folder == ""` select
unrelated repository files. No automatic adaptation is claimed. No empty directories
or private `.obsidian` state are delivered by this package.

## Selection contract (for people and static checks)

| View | Inclusion conditions | Exclusions / limit |
|---|---|---|
| Documents / Working knowledge | `.md`, ID, draft/proposed/accepted text; a listed knowledge kind; root navigation or documented foundation/instructions/architecture/scenarios/decisions/plans/research/guides directory | `_templates`, archive, `_work`, assets, views; template/snapshot/handoff/verification/journal outcomes are not active knowledge rows |
| Documents / Accepted architecture | Above plus `architecture/`, `kind: architecture`, `status: accepted` | This accepts the description's scope, not runtime/release certification |
| Documents / Instructions | Above plus `instructions/`, `kind: instruction` | Shows read conditions, not automatic loading |
| Scenarios | `scenarios/`, `.md`, ID, `kind: scenario`, draft/proposed/accepted | Templates/archive/temporary work excluded; accepted scenario is not implemented function |
| Guides and languages | `guides/`, `.md`, ID, `kind: guide`, draft/proposed/accepted | Language, source edition, checked edition and review summary shown, not inferred from modification dates |
| Translations to reconcile | Guide row with `translation_source` and state other than current | No cross-file ID/revision join is performed by this view; a stale incorrectly labeled current row needs external reconciliation |

`_work/` is only a documented exclusion for temporary task outputs **if** the project
uses that directory; it need not be created. Raw service results should not be in
active knowledge directories. A wrongly classified file can still pass a predicate:
metadata validation and human responsibility checks remain necessary.

A straightforward positive check: a new `docs/architecture/<any-name>.md` with a
unique ID, `kind: architecture` and accepted status satisfies the intended Accepted
architecture conditions, without modifying any filename list. The same content with
`kind: template`, proposed status, in `docs/_templates/`, or in `docs/archive/` does
not. A new `docs/scenarios/<any-name>.md` scenario or
`docs/guides/<language>/<any-name>.md` guide likewise needs no hardcoded list update.
This is a static comparison to the documented predicates, not evaluation/render proof.

## Translation and editing caveats

The source ID and revision fields are defined in one shared schema. Compare primary
`source_revision` against translation `translation_source_revision` through the
linked primary/ID; reconcile the review-summary `translation_state` on content change
and before release. Revision mismatch overrides any stale current label; absent
source means unknown. Dates matching proves nothing. These views do not resolve
IDs or judge translation quality. A deferred translation keeps its warning in text.

Editing a property/table cell can modify the underlying Markdown. A YAML parse is
not proof of rendered views, evaluated filters, property types surviving a GUI
round-trip, or read-only behavior. No GUI verification is required or claimed here.
Use the existing project check for metadata/local links, inspect the YAML structure
and apply the selection contract to synthetic positives/negatives; keep renderer
and client claims separate.

## Templates and diagrams

Package `.md.tmpl` files are agent-filled forms with `{{field_name}}` placeholders,
not ready core-Templates snippets. Copy only their payload and fill/recalculate it.
Obsidian's core Templates supports its documented title/date/time variables; it does
not automatically understand arbitrary project fields. Do not register every package
form in a vault as if it were an accepted project document.

Mermaid remains fenced source in the real architecture/scenario document. A useful
new diagram needs a meaning check and available-renderer check; an unchanged diagram
needs no ritual rerender. Table selections themselves are not architecture diagrams.

## Primary references

Format/syntax checked against the official Obsidian help sources on 2026-10-19;
no third-party package or help text is bundled:

- [Bases syntax](https://help.obsidian.md/bases/syntax)
- [Bases functions](https://help.obsidian.md/bases/functions)
- [Core Templates](https://help.obsidian.md/plugins/templates)
- [Official help source: Bases syntax](https://github.com/obsidianmd/obsidian-help/blob/master/en/Bases/Bases%20syntax.md)
- [Official help source: Functions](https://github.com/obsidianmd/obsidian-help/blob/master/en/Bases/Functions.md)
- [Official help source: Templates](https://github.com/obsidianmd/obsidian-help/blob/master/en/Plugins/Templates.md)

The publish site denied the author request (HTTP403); the same official source
repository supplied the syntax/functions/template-variable definitions (HTTP200).
No Obsidian instance, plugin configuration or personal vault was touched.
