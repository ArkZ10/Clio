#!/usr/bin/env python3
import sys
import os
import sqlite3
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect, init_db
from sqlite_vec import serialize_float32


def run_smoke_test():
    try:
        # Step 1: Delete existing DB and recreate
        if DB_PATH.exists():
            DB_PATH.unlink()
        init_db(DB_PATH)
        print("✓ Step 1: Database created fresh")

        # Step 2: Verify all tables exist
        db = connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' OR type='view'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        required_tables = {"paper", "vec_bge_m3", "vec_specter2"}
        if not required_tables.issubset(tables):
            print(f"✗ Step 2 FAILED: Missing tables. Found: {tables}")
            db.close()
            return False

        print(f"✓ Step 2: All required tables exist: {sorted(tables)}")

        # Step 3: Insert and read back a paper
        cursor.execute(
            """
            INSERT INTO paper (title, abstract, source)
            VALUES (?, ?, ?)
            """,
            ("Test Paper Title", "A short abstract for testing", "library"),
        )
        db.commit()

        cursor.execute("SELECT id FROM paper ORDER BY id DESC LIMIT 1")
        paper_id = cursor.fetchone()[0]

        cursor.execute(
            "SELECT title, abstract, source FROM paper WHERE id = ?", (paper_id,)
        )
        row = cursor.fetchone()
        if row is None or row[0] != "Test Paper Title" or row[2] != "library":
            print(f"✗ Step 3 FAILED: Paper data mismatch. Got: {row}")
            db.close()
            return False

        print(f"✓ Step 3: Paper inserted and retrieved successfully (id={paper_id})")

        # Step 4: Insert a random 1024-dim vector into vec_bge_m3
        vector_1024 = np.random.randn(1024).astype(np.float32)
        vector_serialized = serialize_float32(vector_1024)

        cursor.execute(
            "INSERT INTO vec_bge_m3 (paper_id, embedding) VALUES (?, ?)",
            (paper_id, vector_serialized),
        )
        db.commit()
        print(f"✓ Step 4: 1024-dim vector inserted into vec_bge_m3")

        # Step 5: Run KNN query with a second random vector
        query_vector = np.random.randn(1024).astype(np.float32)
        query_serialized = serialize_float32(query_vector)

        cursor.execute(
            "SELECT paper_id, distance FROM vec_bge_m3 WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (query_serialized, 5),
        )
        results = cursor.fetchall()

        if not results or len(results) == 0:
            print(f"✗ Step 5 FAILED: KNN query returned no results")
            db.close()
            return False

        print(
            f"✓ Step 5: KNN query successful, returned {len(results)} result(s)"
        )
        print(f"  - First result: paper_id={results[0][0]}, distance={results[0][1]:.6f}")

        db.close()
        print("\n✓ SMOKE TEST PASSED")
        return True

    except Exception as e:
        print(f"✗ SMOKE TEST FAILED with exception:")
        print(f"  {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
