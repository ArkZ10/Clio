#!/usr/bin/env python3
"""Generates a dbgate-friendly copy of the database. dbgate (and any SQLite
client without the sqlite-vec extension) can't open a database with vec0
virtual tables -- this produces a browse-only copy with those removed.

The copy is a snapshot; re-run after new ingests to refresh it.
Point dbgate at: data/clio_browse.db
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect

BROWSE_PATH = DB_PATH.parent / "clio_browse.db"

# Virtual tables that use the vec0 module (and break non-extension clients)
VEC_TABLES = ["vec_bge_m3", "vec_specter2"]


def main():
    if not DB_PATH.exists():
        print(f"✗ Source database not found: {DB_PATH}")
        sys.exit(1)

    # Start from a fresh copy of the real database
    shutil.copyfile(DB_PATH, BROWSE_PATH)

    # Drop the vec0 virtual tables. This requires the sqlite-vec module to be
    # loaded (to run the virtual table's destructor), which connect() does.
    db = connect(BROWSE_PATH)
    cursor = db.cursor()
    for table in VEC_TABLES:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    db.commit()
    cursor.execute("VACUUM")
    db.commit()
    db.close()

    print(f"✓ Browse copy written: {BROWSE_PATH}")
    print(f"  Removed vec0 virtual tables: {', '.join(VEC_TABLES)}")
    print(f"  Point dbgate at this file (snapshot -- re-run after new ingests).")


if __name__ == "__main__":
    main()
