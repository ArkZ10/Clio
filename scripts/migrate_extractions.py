#!/usr/bin/env python3
"""Migration: creates the `extractions` table, add-only, never alters paper.
One row per paper (UNIQUE paper_id), so re-running run_extract replaces
rather than duplicates.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS extractions (
    paper_id            INTEGER UNIQUE REFERENCES paper(id),
    problem_value       TEXT,
    problem_span        TEXT,
    method_value        TEXT,
    method_span         TEXT,
    result_value        TEXT,
    result_span         TEXT,
    contribution_value  TEXT,
    contribution_span   TEXT,
    problem_score       REAL,
    method_score        REAL,
    result_score        REAL,
    contribution_score  REAL,
    extract_status      TEXT NOT NULL,
    extract_model       TEXT,
    extracted_at        TEXT
)
"""


def main():
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(CREATE_SQL)
    db.commit()

    print("=== extractions table schema ===")
    cur.execute("PRAGMA table_info(extractions)")
    for row in cur.fetchall():
        nn = " NOT NULL" if row[3] else ""
        print(f"  {row[1]:20} {row[2]:8}{nn}")

    print()
    print("=== paper table untouched (column count) ===")
    cur.execute("PRAGMA table_info(paper)")
    print(f"  paper still has {len(cur.fetchall())} columns")

    db.close()


if __name__ == "__main__":
    main()
