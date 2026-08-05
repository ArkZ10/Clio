"""Per-paper markdown cache: parse a PDF with pymupdf4llm at most once per
parser version, then serve the stored text on later extractions. A version
change is a cache miss -- re-parsed and overwritten.

Only creates/fills/serves the cache; wiring run_extract.py to read through it
is a separate follow-up.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pymupdf4llm

# Derived at runtime so a pymupdf4llm upgrade auto-invalidates the cache.
PARSER_VERSION = f"pymupdf4llm-{pymupdf4llm.__version__}"


def parse_markdown(pdf_path: str | Path) -> str:
    """Identical to run_extract.py's call, no post-processing."""
    return pymupdf4llm.to_markdown(str(pdf_path))


def _cache_valid(row_parser: str | None) -> bool:
    """Usable iff produced by the current parser version."""
    return row_parser == PARSER_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert(db, paper_id: int, markdown: str) -> None:
    db.execute(
        """
        INSERT OR REPLACE INTO paper_text
            (paper_id, markdown, char_count, parser, cached_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (paper_id, markdown, len(markdown), PARSER_VERSION, _now()),
    )
    db.commit()


def get_or_parse_markdown(paper_id: int, pdf_path: str | Path, db) -> tuple[str, str]:
    """(markdown, status), status "HIT" or "MISS". HIT: a row exists for the
    current parser version, returned as-is. MISS: no row or a stale parser
    version -- parsed fresh, upserted, and returned."""
    cur = db.execute(
        "SELECT markdown, parser FROM paper_text WHERE paper_id = ?", (paper_id,)
    )
    row = cur.fetchone()
    if row is not None and _cache_valid(row[1]):
        return row[0], "HIT"

    markdown = parse_markdown(pdf_path)
    _upsert(db, paper_id, markdown)
    return markdown, "MISS"
