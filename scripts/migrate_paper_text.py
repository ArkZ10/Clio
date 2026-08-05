#!/usr/bin/env python3
"""Add-only migration: creates the `paper_text` markdown cache table. Doesn't
alter `paper` or `extractions`. One row per paper.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

CREATE = """
CREATE TABLE IF NOT EXISTS paper_text (
    paper_id    INTEGER PRIMARY KEY,   -- FK -> paper.id, one row per paper
    markdown    TEXT NOT NULL,
    char_count  INTEGER,
    parser      TEXT,                  -- e.g. "pymupdf4llm-1.27.2.3"
    cached_at   TEXT                   -- ISO timestamp
)
"""


def main():
    db = connect(DB_PATH)
    db.execute(CREATE)
    db.commit()

    print("=" * 70)
    print("STEP 1: paper_text schema")
    print("-" * 70)
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='paper_text'"
    ).fetchone()
    print(row[0] if row else "(table not found!)")
    print()
    print("column detail (PRAGMA table_info):")
    for cid, name, ctype, notnull, dflt, pk in db.execute(
        "PRAGMA table_info(paper_text)"
    ):
        flags = []
        if pk:
            flags.append("PK")
        if notnull:
            flags.append("NOT NULL")
        print(f"  {name:11} {ctype:8} {' '.join(flags)}")
    print("=" * 70)
    db.close()


if __name__ == "__main__":
    main()
