"""Per-paper markdown cache: parse a PDF with pymupdf4llm at most once per
parser version, then serve the stored text on subsequent (re-)extractions.

Justification is RE-PARSE AVOIDANCE. The stored text is BYTE-IDENTICAL to what
run_extract.py currently parses -- `pymupdf4llm.to_markdown(str(path))` with no
added cleaning/normalization -- so a cache hit is indistinguishable from a fresh
parse. A parser-version guard (the `parser` column) protects against serving
text produced by a different pymupdf4llm version: a version change is treated as
a cache MISS and the text is re-parsed + overwritten.

This module only CREATES/FILLS/serves the cache. Wiring run_extract.py to read
through it is a separate follow-up.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pymupdf4llm

# The parser tag stored alongside every cached row. Derived from the installed
# version at runtime so a pymupdf4llm upgrade automatically invalidates the
# cache (mismatch => MISS => re-parse + overwrite).
PARSER_VERSION = f"pymupdf4llm-{pymupdf4llm.__version__}"


def parse_markdown(pdf_path: str | Path) -> str:
    """The ONE parse, identical to run_extract.py's call. No post-processing."""
    return pymupdf4llm.to_markdown(str(pdf_path))


def _cache_valid(row_parser: str | None) -> bool:
    """A cached row is usable iff it was produced by the current parser version.
    A mismatch (or missing tag) is stale -> treated as a MISS."""
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
    """Return (markdown, status) where status is "HIT" or "MISS".

    HIT  -> a row exists AND its parser == the current pymupdf4llm version;
            the stored text is returned, the PDF is NOT re-parsed.
    MISS -> no row, OR the row's parser is stale; the PDF is parsed via
            `parse_markdown` (exactly as extraction does), the row is upserted,
            and the fresh text is returned. (A parser-version mismatch is a MISS
            and overwrites the stale row.)
    """
    cur = db.execute(
        "SELECT markdown, parser FROM paper_text WHERE paper_id = ?", (paper_id,)
    )
    row = cur.fetchone()
    if row is not None and _cache_valid(row[1]):
        return row[0], "HIT"

    markdown = parse_markdown(pdf_path)
    _upsert(db, paper_id, markdown)
    return markdown, "MISS"
