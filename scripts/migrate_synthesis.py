#!/usr/bin/env python3
"""Step 1: ADD-ONLY migration -- create the F4c synthesis persistence tables.

Does NOT alter paper / extractions / paper_text / cluster / paper_cluster.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS synthesis_run (
        id              INTEGER PRIMARY KEY,
        exploration_id  INTEGER,
        created_at      TEXT,
        n_camps         INTEGER,
        n_scattered     INTEGER,
        overview        TEXT,
        model           TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS synthesis_cluster (
        id           INTEGER PRIMARY KEY,
        run_id       INTEGER NOT NULL REFERENCES synthesis_run(id),
        cluster_id   INTEGER NOT NULL,
        theme        TEXT,
        claims_json  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS synthesis_toplevel_item (
        id               INTEGER PRIMARY KEY,
        run_id           INTEGER NOT NULL REFERENCES synthesis_run(id),
        kind             TEXT,   -- 'claim' | 'tension' | 'open_problem'
        text             TEXT,
        cluster_ids_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS synthesis_cluster_member (
        run_id      INTEGER NOT NULL REFERENCES synthesis_run(id),
        cluster_id  INTEGER NOT NULL,
        paper_id    INTEGER NOT NULL,
        PRIMARY KEY (run_id, cluster_id, paper_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS synthesis_scattered (
        run_id    INTEGER NOT NULL REFERENCES synthesis_run(id),
        paper_id  INTEGER NOT NULL,
        reason    TEXT,   -- 'noise' | 'folded_small_cluster'
        PRIMARY KEY (run_id, paper_id)
    )
    """,
]

TABLE_NAMES = [
    "synthesis_run",
    "synthesis_cluster",
    "synthesis_toplevel_item",
    "synthesis_cluster_member",
    "synthesis_scattered",
]


def main():
    db = connect(DB_PATH)
    for stmt in CREATE_STATEMENTS:
        db.execute(stmt)
    db.commit()

    print("=" * 78)
    print("STEP 1: synthesis persistence schema (F4c)")
    print("-" * 78)
    for name in TABLE_NAMES:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        print(row[0] if row else f"(table {name} not found!)")
        print()
    print("=" * 78)
    db.close()


if __name__ == "__main__":
    main()
