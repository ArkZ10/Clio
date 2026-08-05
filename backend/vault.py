"""Read an Obsidian vault and build its wikilink graph.

Pure functions, read-only: no DB, no network, no writes.

templates/ and CLAUDE.md are excluded (their example links point at pages that
will never exist). raw/ is excluded too -- it holds PDFs, not wiki pages, and
one of its filenames collides with a wiki/sources/ stem. Dotfolders excluded
outright.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# wiki/<subfolder>/ -> category of the same name; everything else is "root".
WIKI_CATEGORIES = (
    "sources",
    "claims",
    "concepts",
    "entities",
    "questions",
    "syntheses",
)
ROOT_CATEGORY = "root"
CATEGORIES = (*WIKI_CATEGORIES, ROOT_CATEGORY)

# Directories skipped entirely (matched on the first path segment).
EXCLUDED_DIRS = {"templates", "raw"}
# Individual files skipped (matched on the vault-relative path).
EXCLUDED_FILES = {"CLAUDE.md"}

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
# \| required, not defensive -- wikilinks inside GFM tables escape the pipe
# so it doesn't terminate the cell.
_ALIAS_SPLIT_RE = re.compile(r"\\?\|")


def categorize(rel_path: Path) -> str:
    """Category for a vault-relative path. wiki/<sub>/x.md -> <sub>; anything
    else in scope (wiki/overview.md, index.md, log.md) -> 'root'."""
    parts = rel_path.parts
    if len(parts) >= 3 and parts[0] == "wiki" and parts[1] in WIKI_CATEGORIES:
        return parts[1]
    return ROOT_CATEGORY


def _in_scope(rel_path: Path) -> bool:
    parts = rel_path.parts
    if any(part.startswith(".") for part in parts):
        return False
    if parts[0] in EXCLUDED_DIRS:
        return False
    if rel_path.as_posix() in EXCLUDED_FILES:
        return False
    return True


def scan_vault(vault_path: str | Path) -> list[dict]:
    """Every in-scope markdown page as {rel_path, stem, category, text},
    sorted by rel_path for deterministic output."""
    root = Path(vault_path)
    records = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if not _in_scope(rel):
            continue
        records.append(
            {
                "rel_path": rel.as_posix(),
                "stem": path.stem,
                "category": categorize(rel),
                "text": path.read_text(encoding="utf-8", errors="replace"),
            }
        )
    return records


def split_frontmatter(text: str) -> tuple[dict, str]:
    """(metadata, body) -- splits out the leading YAML block so the UI can
    show it as structured metadata instead of raw `key: value` text. A
    malformed or non-dict block degrades to empty metadata, never an
    exception."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text[match.end() :]
    if not isinstance(meta, dict):
        return {}, text[match.end() :]
    return meta, text[match.end() :]


def strip_code(text: str) -> str:
    """Blanks fenced blocks and inline spans so code samples can't emit edges
    -- log.md documents the citation convention as an inline-code example,
    which is prose about a link, not a link."""
    text = _FENCED_CODE_RE.sub("", text)
    return _INLINE_CODE_RE.sub("", text)


def parse_links(text: str) -> list[str]:
    """Wikilink targets, in order, after stripping code. Handles `[[Page]]`,
    `[[Page|alias]]`, the escaped-pipe table form, and defensively
    `folder/Page`, `Page#Heading`, `Page^block`. Frontmatter is NOT stripped
    -- `sources:` holds real citation links."""
    targets = []
    for inner in _WIKILINK_RE.findall(strip_code(text)):
        target = _ALIAS_SPLIT_RE.split(inner, maxsplit=1)[0]
        target = target.split("#", 1)[0].split("^", 1)[0]
        target = target.rsplit("/", 1)[-1].strip()
        if target:
            targets.append(target)
    return targets


def build_graph(vault_path: str | Path) -> dict:
    """{nodes, links, unresolved}. A link only emits if its target resolves
    to a real page -- unresolved targets are reported, never a phantom node.
    Edges are undirected and deduped; self-links dropped."""
    records = scan_vault(vault_path)

    nodes = [
        {"id": r["stem"], "title": r["stem"], "category": r["category"]}
        for r in records
    ]
    by_stem = {r["stem"]: r for r in records}
    # Obsidian resolves links case-insensitively.
    lower_to_stem = {stem.lower(): stem for stem in by_stem}

    seen_pairs: set[tuple[str, str]] = set()
    links = []
    unresolved = []

    for record in records:
        source = record["stem"]
        for target in parse_links(record["text"]):
            resolved = target if target in by_stem else lower_to_stem.get(target.lower())
            if resolved is None:
                unresolved.append({"source": source, "target": target})
                continue
            if resolved == source:
                continue  # self-link: real in prose, meaningless as an edge
            pair = (source, resolved) if source < resolved else (resolved, source)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            links.append({"source": pair[0], "target": pair[1]})

    return {"nodes": nodes, "links": links, "unresolved": unresolved}


def graph_stats(graph: dict) -> dict:
    """n_nodes / n_links / n_unresolved / n_orphans, where an orphan is a node
    with zero edges (in or out) -- a page nothing links to and that links
    nowhere resolvable."""
    degree: dict[str, int] = {node["id"]: 0 for node in graph["nodes"]}
    for link in graph["links"]:
        degree[link["source"]] += 1
        degree[link["target"]] += 1
    return {
        "n_nodes": len(graph["nodes"]),
        "n_links": len(graph["links"]),
        "n_unresolved": len(graph["unresolved"]),
        "n_orphans": sum(1 for d in degree.values() if d == 0),
    }


def list_sources(vault_path: str | Path) -> list[dict]:
    """wiki/sources pages with a real PDF attached via `raw:` -- the Library
    feature's paper list. Not every sources/ page is a paper (the idea-file
    note lives there too, `raw:` pointing at .md not a PDF), so those are
    filtered out. Doesn't check the PDF actually exists -- find_source_pdf
    does that at fetch time.
    """
    out = []
    for record in scan_vault(vault_path):
        if record["category"] != "sources":
            continue
        meta, _ = split_frontmatter(record["text"])
        raw = meta.get("raw")
        if not isinstance(raw, str) or not raw.lower().endswith(".pdf"):
            continue
        authors = meta.get("authors")
        out.append(
            {
                "stem": record["stem"],
                "title": str(meta.get("title") or record["stem"]),
                "authors": authors if isinstance(authors, list) else [],
                "year": meta.get("year") if isinstance(meta.get("year"), int) else None,
                "venue": meta.get("venue"),
                "evidence": meta.get("evidence"),
                "status": meta.get("status"),
            }
        )
    # Newest first; undated entries (shouldn't normally happen) sort last.
    out.sort(key=lambda p: (p["year"] is None, -(p["year"] or 0), p["title"]))
    return out


def find_source_pdf(vault_path: str | Path, stem: str) -> Path | None:
    """The PDF a wiki/sources page's `raw:` field points at, or None if the
    page/field/file doesn't exist. Containment-checked the same as find_page's
    `stem`, even though `raw:` is vault content, not request input."""
    root = Path(vault_path).resolve()
    page = find_page(root, stem)
    if page is None or page["category"] != "sources":
        return None
    raw = page["meta"].get("raw")
    if not isinstance(raw, str) or not raw.lower().endswith(".pdf"):
        return None
    resolved = (root / raw).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def find_page(vault_path: str | Path, stem: str) -> dict | None:
    """One in-scope page by filename stem, or None. `stem` comes from a URL
    path segment, so containment is checked -- a `../../etc/passwd` traversal
    fails both the stem match and the containment check."""
    root = Path(vault_path).resolve()
    for record in scan_vault(root):
        if record["stem"] != stem:
            continue
        resolved = (root / record["rel_path"]).resolve()
        if not resolved.is_relative_to(root):
            return None
        meta, body = split_frontmatter(record["text"])
        return {
            "stem": record["stem"],
            "category": record["category"],
            "path": record["rel_path"],
            "content": body,  # body only -- YAML returned separately as meta
            "meta": meta,
            "title": str(meta.get("title") or record["stem"]),
        }
    return None
