#!/usr/bin/env python3
"""Read-only, explicit-scope documentation checks. No application imports or fixes."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import yaml
except ImportError:
    print(json.dumps({"exit_code": 2, "findings": [{"code": "dependency.missing", "severity": "error", "message": "Install pack/tools/requirements.txt in an isolated tooling environment"}]}))
    raise SystemExit(2)

STATUSES = {"draft", "proposed", "accepted", "superseded", "archived"}
REQUIRED = ("id", "title", "kind", "status", "created", "updated", "areas", "summary")
KINDS = {"philosophy", "engineering_policy", "instruction", "architecture", "contract", "reference", "scenario", "proposal", "plan", "decision", "research", "incident", "guide", "verification", "journal", "handoff", "snapshot", "template", "navigation"}
OPTIONAL_TEXT = ("read_when", "owner", "release_owner", "language", "source_revision", "translation_source", "translation_source_revision", "translation_state", "snapshot_of", "version", "code_ref", "verification_scope", "review_note")
CLASSES = {"authoring", "native", "templates"}
TEXT_SUFFIXES = (".md", ".md.tmpl", ".yaml", ".yml", ".yaml.tmpl", ".base")
TOKEN = re.compile(r"\{\{[^{}\n]+\}\}")


class InputError(ValueError):
    """Invalid boundary, unreadable input or invalid corpus, never an empty success."""


class UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML without aliases/anchors; repeated mappings never use last-key wins."""

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML anchors and aliases are not part of this schema")
        return super().compose_node(parent, index)


def unique_mapping(loader, node, deep=False):
    if any(key.tag == "tag:yaml.org,2002:merge" for key, _ in node.value):
        raise ValueError("YAML merge keys are not part of this schema")
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as error:
            raise ValueError("YAML mapping key must be a scalar") from error
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def safe_yaml(text):
    return yaml.load(text, Loader=UniqueSafeLoader)


def bounded(root, relative):
    """Resolve without permitting absolute/traversal/symlink access outside scope."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise InputError("Use a nonempty root-relative forward-slash path")
    path = Path(relative)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", relative) or ".." in path.parts:
        raise InputError("Absolute paths and parent traversal are not corpus entries")
    target = root / path
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InputError("Symlinks are not selected inputs")
    if not target.resolve().is_relative_to(root):
        raise InputError("Path escapes selected root")
    return target


def read_text(path):
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise InputError("Selected text must exist and be at most 1 MiB")
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise InputError("Selected text is unreadable UTF-8") from error


def frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("Initial YAML frontmatter is required")
    end = next((i for i, line in enumerate(lines[1:], 1) if line == "---"), None)
    if end is None:
        raise ValueError("Unclosed frontmatter")
    value = safe_yaml("\n".join(lines[1:end]))
    if not isinstance(value, dict):
        raise ValueError("Frontmatter must be a mapping")
    return value, "\n".join(lines[end + 1:])


def unfenced(text):
    """Remove common fenced blocks before role-specific inline processing."""
    result, fence = [], None
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            mark = match.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            result.append(line)
    return "\n".join(result)


def code_spans(text):
    """Pair complete, equally long backtick runs; unmatched runs stay literal.

    This bounded subset supports multiline spans, not all CommonMark constructs.
    Return offsets so link labels keep their original reference-key identity.
    """
    runs = list(re.finditer(r"`+", text))
    following, next_equal = {}, {}
    for index in range(len(runs) - 1, -1, -1):
        size = len(runs[index][0])
        if size in next_equal:
            following[index] = next_equal[size]
        next_equal[size] = index
    spans, index = [], 0
    while index < len(runs):
        end = following.get(index)
        if end is None:
            index += 1
        else:
            spans.append((runs[index].start(), runs[end].end(), len(runs[index][0])))
            index = end + 1
    return spans


def mask_code(text, spans):
    chars = list(text)
    for start, end, _ in spans:
        chars[start:end] = ["\n" if c == "\n" else " " for c in text[start:end]]
    return "".join(chars)


def visible(text):
    """Literal-free view for syntax that cannot contain inline code (IDs/wiki)."""
    text = unfenced(text)
    return mask_code(text, code_spans(text))


def local_links(text):
    text = unfenced(text)
    syntax = mask_code(text, code_spans(text))
    definitions = {}
    for match in re.finditer(r"(?m)^[ \t]{0,3}\[([^\]\n]+)\]:\s*(?:<([^>]+)>|(\S+))", text):
        opener = match.start() + match[0].index("[")
        if syntax[opener] == "[" and not match[1].startswith("^"):
            definitions[match[1].casefold()] = match[2] or match[3]
    targets = [m[1] or m[2] for m in re.finditer(r"!?\[[^\]\n]+\]\(\s*(?:<([^>\n]+)>|([^\s()]+))(?:\s+\"[^\"]*\")?\s*\)", text)
               if syntax[m.start()] != " "]
    missing = []
    for match in re.finditer(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]", text):
        if syntax[match.start()] == " ":
            continue
        key = (match[2] or match[1]).casefold()
        if key in definitions:
            targets.append(definitions[key])
        else:
            missing.append(key)
    return targets, missing


def anchors(text):
    text = unfenced(text)
    syntax = mask_code(text, code_spans(text))
    result = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", syntax))
    used = {}
    for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", text):
        if syntax[match.start()] != "#":
            continue
        heading = match[1]
        for start, end, size in reversed(code_spans(heading)):
            heading = heading[:start] + heading[start + size:end - size] + heading[end:]
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = used.get(slug, 0)
        used[slug] = count + 1
        result.add(slug + (f"-{count}" if count else ""))
    return result


class Checker:
    def __init__(self, root, corpus, mode):
        self.root, self.corpus, self.mode = root, corpus, mode
        self.findings, self.docs, self.bodies, self.translations = [], {}, {}, []
        self.checked, self.external_links = 0, 0

    def add(self, path, code, message, severity="error"):
        self.findings.append(dict(path=path, code=code, severity=severity, message=message))

    def metadata(self, path, data, body):
        for key in REQUIRED:
            value = data.get(key)
            valid = isinstance(value, list) and bool(value) and all(type(x) is str and x.strip() and not TOKEN.search(x) for x in value) if key == "areas" else type(value) is str and bool(value.strip())
            if not valid or (isinstance(value, str) and TOKEN.search(value)):
                self.add(path, "metadata.type", f"Required {key}: nonempty string (areas: nonempty string list), no placeholders")
        for key in OPTIONAL_TEXT:
            if key in data and (type(data[key]) is not str or not data[key].strip()):
                self.add(path, "metadata.type", f"Optional {key} must be a nonempty string")
            elif key in data and TOKEN.search(data[key]):
                self.add(path, "placeholder.metadata", f"Unfilled {key} in output metadata")
        for key in ("related", "supersedes", "issue_refs", "evidence_refs"):
            if key in data and (not isinstance(data[key], list) or not all(type(x) is str and x.strip() for x in data[key])):
                self.add(path, "metadata.type", f"Optional {key} must be a string list")
        if type(data.get("status")) is not str or data["status"] not in STATUSES:
            self.add(path, "metadata.status", "Unknown document status")
        if type(data.get("kind")) is not str or data["kind"] not in KINDS:
            self.add(path, "metadata.kind", "Unknown kind; extend the single schema and checker deliberately")
        if data.get("kind") == "instruction" and not data.get("read_when"):
            self.add(path, "metadata.trigger", "Instruction needs read_when")
        if "translation_state" in data and data["translation_state"] not in ("current", "outdated", "unknown"):
            self.add(path, "translation.state", "translation_state must be current/outdated/unknown")
        for key in ("created", "updated", "code_verified_at"):
            if key == "code_verified_at" and data.get(key) is None:
                continue
            value = data.get(key)
            try:
                if type(value) is not str or len(value) != 10:
                    raise ValueError()
                date.fromisoformat(value)
            except (ValueError, TypeError):
                self.add(path, "metadata.date", f"{key} must be a quoted ISO YYYY-MM-DD string")
        if TOKEN.search(body):
            self.add(path, "placeholder.output", "Unfilled agent placeholder in output", "error" if data.get("status") == "accepted" else "warning")
        self.docs[path] = data

    def skill(self, path, data):
        name = data.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64 or name != Path(path).parent.name:
            self.add(path, "skill.name", "Skill name must match directory and Agent Skills naming rules")
        description = data.get("description")
        if not isinstance(description, str) or not description.strip() or len(description) > 1024:
            self.add(path, "skill.description", "Skill description must be 1..1024 characters")
        for key, limit in (("compatibility", 500), ("license", None), ("allowed-tools", None)):
            value = data.get(key)
            if key in data and (not isinstance(value, str) or not value.strip() or (limit and len(value) > limit)):
                self.add(path, "skill.field", f"Invalid {key}")
        if "metadata" in data and (not isinstance(data["metadata"], dict) or not all(type(k) is str and type(v) is str for k, v in data["metadata"].items())):
            self.add(path, "skill.metadata", "Skill metadata must map strings to strings")
        if TOKEN.search(str(data)):
            self.add(path, "placeholder.skill", "Skill metadata is not a template")

    def base(self, path, text):
        data = safe_yaml(text)
        if not isinstance(data, dict) or not isinstance(data.get("views"), list) or not data["views"]:
            self.add(path, "base.structure", "Base must map a nonempty views list")
            return
        if "filters" in data and not isinstance(data["filters"], (str, dict, list)):
            self.add(path, "base.structure", "Base filters must be string, mapping or list")
        for view in data["views"]:
            if not isinstance(view, dict) or not isinstance(view.get("type"), str) or not isinstance(view.get("name"), str):
                self.add(path, "base.structure", "Each view needs type and name strings")
        self.add(path, "base.not_rendered", "YAML shape only; filters not evaluated and Obsidian not opened", "not_checked")

    def load(self):
        for path, group in sorted(self.corpus.items()):
            file = bounded(self.root, path)
            if not path.endswith(TEXT_SUFFIXES):
                raise InputError(f"Not a selected documentation format: {path}")
            if group == "templates":
                if not path.endswith(".tmpl"):
                    raise InputError("Only explicit .tmpl inputs may use templates classification")
                read_text(file)  # existence/UTF-8 only; output-relative links are not pack links
                self.checked += 1
                continue
            if path.endswith(".tmpl"):
                raise InputError("Template inputs must be explicitly classified as templates")
            text = read_text(file)
            self.checked += 1
            try:
                if path.endswith(".base"):
                    self.base(path, text)
                elif file.name == "SKILL.md":
                    data, body = frontmatter(text)
                    self.skill(path, data)
                    self.bodies[path] = body
                elif group == "authoring":
                    if not path.endswith(".md") or file.name == "AGENTS.md":
                        raise InputError("Authoring is for durable .md documents, not native formats")
                    data, body = frontmatter(text)
                    self.metadata(path, data, body)
                    self.bodies[path] = body
                elif path.endswith((".yaml", ".yml")):
                    safe_yaml(text)
                    if self.mode == "project" and TOKEN.search(text):
                        self.add(path, "placeholder.native", "Unfilled placeholder in native YAML output")
                else:
                    self.bodies[path] = text  # native Markdown uses its own grammar
                    if file.name == "AGENTS.md" and TOKEN.search(text):
                        self.add(path, "placeholder.native", "Unfilled placeholder in AGENTS output")
            except (yaml.YAMLError, ValueError) as error:
                if isinstance(error, InputError):
                    raise
                self.add(path, "yaml.invalid", str(error))

    def relations(self):
        ids = {}
        for path, data in self.docs.items():
            identity = data.get("id")
            if isinstance(identity, str):
                if identity in ids:
                    self.add(path, "id.duplicate", f"ID also present in {ids[identity]}")
                ids[identity] = path
        for path, data in self.docs.items():
            if data.get("kind") != "guide":
                continue
            if not isinstance(data.get("language"), str) or not data["language"].strip():
                self.add(path, "translation.language", "Guide needs language")
            source_id = data.get("translation_source")
            if source_id is None:
                if not isinstance(data.get("source_revision"), str) or not data["source_revision"].strip():
                    self.add(path, "translation.revision", "Primary guide needs source_revision")
                continue
            source_path = ids.get(source_id) if isinstance(source_id, str) else None
            source = self.docs.get(source_path, {})
            if source_path is None or source_path == path or source.get("kind") != "guide" or source.get("translation_source") is not None:
                self.add(path, "translation.source", "Select the distinct primary guide in this corpus")
                continue
            revision = data.get("translation_source_revision")
            current = source.get("source_revision")
            if not isinstance(revision, str) or not revision.strip():
                self.add(path, "translation.revision", "Translation needs translation_source_revision")
            if "source_revision" in data:
                self.add(path, "translation.revision", "Translation uses checked primary edition, not an independent source_revision")
            if data.get("translation_state") not in ("current", "outdated", "unknown"):
                self.add(path, "translation.state", "Translation needs a human translation_state summary")
            if data.get("language") == source.get("language"):
                self.add(path, "translation.language", "Translation and primary must have different languages")
            matches = isinstance(revision, str) and bool(revision) and revision == current
            state = data.get("translation_state", "unknown") if matches else "outdated"
            self.translations.append(dict(path=path, source=source_path, state=state, revision_match=matches))
            if not matches:
                self.add(path, "translation.outdated", "Translation source revision differs; equal dates are not freshness", "warning")
                if data.get("translation_state") == "current":
                    self.add(path, "translation.contradiction", "Current translation claims a different primary revision")

    def links(self):
        for path, body in self.bodies.items():
            targets, missing = local_links(body)
            for key in missing:
                self.add(path, "link.reference", f"Missing reference definition: {key}")
            for value in targets:
                parts = urlsplit(value)
                if parts.scheme in {"http", "https", "mailto", "tel", "data"}:
                    self.external_links += 1
                    continue
                if parts.scheme or parts.netloc or value.startswith(("/", "\\")):
                    self.add(path, "link.boundary", "Local link must stay within selected root")
                    continue
                relative = unquote(parts.path)
                if "\\" in relative or re.match(r"^[A-Za-z]:", relative):
                    self.add(path, "link.boundary", "Use relative forward-slash links")
                    continue
                candidate = (self.root / path).parent if relative else self.root / path
                unsafe = False
                for part in Path(relative).parts:
                    candidate = candidate.parent if part == ".." else candidate / part
                    if not candidate.is_relative_to(self.root) or candidate.is_symlink():
                        unsafe = True
                        break
                if unsafe:
                    self.add(path, "link.boundary", "Local link escapes root or traverses a symlink")
                    continue
                target = candidate.resolve()
                target_name = target.relative_to(self.root).as_posix()
                if not target.exists():
                    self.add(path, "link.missing", f"Missing local target: {target_name}")
                elif parts.fragment:
                    if target_name not in self.bodies:
                        self.add(path, "link.anchor_scope", f"Anchor outside parsed selection: {target_name}", "not_checked")
                    elif unquote(parts.fragment) not in anchors(self.bodies[target_name]):
                        self.add(path, "link.anchor", f"Missing anchor in {target_name}: {parts.fragment}")
            if "[[" in visible(body):
                self.add(path, "link.wiki", "Wikilinks are outside this bounded Markdown checker", "not_checked")

    def run(self):
        self.load()
        self.relations()
        self.links()
        return dict(mode=self.mode, root=str(self.root), checked=self.checked,
                    exit_code=int(any(f["severity"] == "error" for f in self.findings)),
                    findings=self.findings, translations=self.translations,
                    external_links_not_checked=self.external_links,
                    limitations=["Explicit text selection only; no product imports, network or writes",
                                 "Common Markdown links/headings only; no full Markdown/Bases renderer",
                                 "Templates are UTF-8/existence inputs, not accepted output validation"])


def project_corpus(root, path):
    file = bounded(root, path)
    data = safe_yaml(read_text(file))
    if not isinstance(data, dict) or set(data) - CLASSES:
        raise InputError("Corpus maps only authoring/native/templates to path lists")
    result = {}
    for group, paths in data.items():
        if not isinstance(paths, list):
            raise InputError("Corpus classes must be path lists")
        for path in paths:
            bounded(root, path)
            if path in result:
                raise InputError("Duplicate/conflicting corpus entry")
            result[path] = group
    if not result:
        raise InputError("Empty corpus is not a check")
    return result


def pack_corpus(root):
    if not (root / "skills").is_dir() or not (root / "references").is_dir():
        raise InputError("Pack must contain skills and references")
    result = {}
    for file in root.rglob("*"):
        relative = file.relative_to(root).as_posix()
        if file.is_symlink():
            raise InputError("Pack symlinks are unsupported")
        if file.is_file() and relative.endswith(TEXT_SUFFIXES):
            bounded(root, relative)
            result[relative] = "templates" if relative.endswith(".tmpl") else "native"
    expected = {"pf-bootstrap", "pf-plan", "pf-maintain", "pf-quality", "pf-guides", "pf-ui-design", "pf-command-first"}
    actual = {p.name for p in (root / "skills").iterdir() if p.is_dir()}
    if actual != expected or any(not (root / "skills" / name / "SKILL.md").is_file() for name in expected):
        raise InputError("Pack needs exactly the seven named pf-* skill directories and their SKILL.md")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pack", nargs="?", const=str(Path(__file__).resolve().parents[1]), metavar="ROOT", help="Explicit pack scan; omitted ROOT uses script-relative pack")
    mode.add_argument("--project", type=Path, help="Explicit project read boundary")
    parser.add_argument("--corpus", help="Required root-relative classified YAML/JSON input for --project")
    args = parser.parse_args(argv)
    try:
        if args.pack:
            if args.corpus:
                raise InputError("--corpus is only for --project")
            root = Path(args.pack).resolve()
            corpus = pack_corpus(root)
            mode_name = "pack"
        else:
            if not args.corpus:
                raise InputError("--project requires --corpus")
            root = args.project.resolve()
            corpus = project_corpus(root, args.corpus)
            mode_name = "project"
        report = Checker(root, corpus, mode_name).run()
    except (InputError, OSError, yaml.YAMLError, ValueError) as error:
        report = dict(exit_code=2, findings=[dict(code="input.invalid", severity="error", message=str(error))])
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
