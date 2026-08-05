"""Read an Obsidian vault and build its wikilink graph.

Pure functions: no DB, no network, and NEVER any writes -- the vault is treated
as strictly read-only input.

Scope decisions (each one is load-bearing; see the notes on the constants):
  - `templates/` and `CLAUDE.md` are excluded because they are schema/skeleton
    documents whose example links (`[[Page A]]`, `[[citation-key]]`, ...) point
    at pages that will never exist. Including them injects ~20 phantom broken
    links that are noise, not signal.
  - `raw/` is excluded because it holds immutable sources (PDFs), not wiki
    pages, AND because raw/2026-08-03-llm-wiki-idea-file.md shares a filename
    stem with wiki/sources/ -- since node ids are stems, including raw/ would
    collide on the vault's single most-linked page.
  - Dotfolders (.obsidian/, .git/) are excluded outright.

With that scope the vault currently resolves every single wikilink, so a
non-zero unresolved count is a genuine signal (a real broken link, or a parser
regression) rather than expected background noise.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# wiki/<subfolder>/ maps to a category of the same name; everything else that is
# in scope (wiki/overview.md, index.md, log.md) is "root".
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
# Alias separator. The escaped form `\|` is REQUIRED, not defensive: wikilinks
# inside GFM tables escape the pipe so it does not terminate the table cell, and
# the claim-ledger evidence tables (the densest real edges in the vault) are all
# written that way. Splitting on a bare `|` alone mangles every one of them.
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
    """Every in-scope markdown page. Read-only.

    Returns records of {rel_path, stem, category, text}, sorted by rel_path so
    output is deterministic across runs.
    """
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
    """(metadata, body) for a page.

    Every vault page opens with a YAML block. Handing that raw block to a
    markdown renderer produces a wall of `key: value` text, so it is parsed out
    here and returned separately for the UI to present as structured metadata.
    A malformed or non-dict block degrades to empty metadata with the body
    untouched -- never an exception.
    """
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
    """Blank out fenced blocks and inline spans so code samples can't emit edges.

    Fenced blocks are the documented requirement. Inline spans matter too: log.md
    documents the citation convention as `` `[[key|Author et al. Year]]` ``,
    which is prose about a link, not a link.
    """
    text = _FENCED_CODE_RE.sub("", text)
    return _INLINE_CODE_RE.sub("", text)


def parse_links(text: str) -> list[str]:
    """Wikilink targets, in order of appearance, after stripping code.

    Handles `[[Page]]`, `[[Page|alias]]`, `[[Page\\|alias]]` (escaped pipe, used
    in tables), and defensively `[[folder/Page]]`, `[[Page#Heading]]`,
    `[[Page^block]]` -- none of the last three occur today but they are cheap to
    tolerate. Frontmatter is deliberately NOT stripped: the `sources:` field
    holds real citation links (claim -> the paper it rests on).
    """
    targets = []
    for inner in _WIKILINK_RE.findall(strip_code(text)):
        target = _ALIAS_SPLIT_RE.split(inner, maxsplit=1)[0]
        target = target.split("#", 1)[0].split("^", 1)[0]
        target = target.rsplit("/", 1)[-1].strip()
        if target:
            targets.append(target)
    return targets


def build_graph(vault_path: str | Path) -> dict:
    """{nodes, links, unresolved} for the vault's wikilink graph.

    Links are emitted only where the target resolves to a real page -- an
    unresolved target is reported, never turned into a phantom node. Edges are
    undirected and deduped; self-links are dropped.
    """
    records = scan_vault(vault_path)

    nodes = [
        {"id": r["stem"], "title": r["stem"], "category": r["category"]}
        for r in records
    ]
    by_stem = {r["stem"]: r for r in records}
    # Case-insensitive fallback: Obsidian resolves links case-insensitively, and
    # every link in the vault is currently exact-case, so this only ever helps.
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
    """wiki/sources pages that have a real PDF attached via a `raw:` frontmatter
    field ending in .pdf -- this is the Library feature's paper list.

    Not every page under wiki/sources/ is a paper: 2026-08-03-llm-wiki-idea-file
    lives there too with `raw:` pointing at a .md scratch file, not a PDF, so it
    is filtered out rather than shown as a fake library entry. Existence of the
    PDF file itself is NOT checked here (that's find_source_pdf's job, at fetch
    time) -- this only reflects what the notes claim to have.
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
    page, the field, or the file doesn't exist.

    `raw:` is vault content (the user's own notes), not request input, but it
    is still containment-checked the same way find_page checks `stem` -- never
    trust a path out of a file without verifying where it actually points.
    """
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
    """One in-scope page by filename stem, or None.

    `stem` arrives from a URL path segment, so the resolved file is checked to
    be inside the vault and inside the allowed scope -- a traversal attempt like
    `../../etc/passwd` fails both the stem match and the containment check.
    """
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
            # `content` is the body only -- the YAML block is returned parsed as
            # `meta` so the UI can render it as metadata rather than prose.
            "content": body,
            "meta": meta,
            "title": str(meta.get("title") or record["stem"]),
        }
    return None
