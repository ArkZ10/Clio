#!/usr/bin/env python3
"""Neighbor-inspection CLI -- the gate for judging embedding quality."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect

VEC_TABLE = "vec_bge_m3"


def list_papers(db):
    cursor = db.cursor()
    cursor.execute(
        f"""
        SELECT p.id, p.title
        FROM paper p
        JOIN {VEC_TABLE} v ON v.paper_id = p.id
        ORDER BY p.id
        """
    )
    for paper_id, title in cursor.fetchall():
        title_str = (title or "")[:60]
        print(f"{paper_id}: {title_str}")


def neighbors(db, paper_id):
    cursor = db.cursor()

    cursor.execute(f"SELECT 1 FROM {VEC_TABLE} WHERE paper_id = ?", (paper_id,))
    if cursor.fetchone() is None:
        print(f"No embedding found for paper_id={paper_id}")
        return

    used_fallback = False
    try:
        cursor.execute(
            f"""
            SELECT v.paper_id, v.distance, p.title
            FROM {VEC_TABLE} v
            JOIN paper p ON p.id = v.paper_id
            WHERE v.embedding MATCH (SELECT embedding FROM {VEC_TABLE} WHERE paper_id = ?)
              AND k = 6
            ORDER BY v.distance
            """,
            (paper_id,),
        )
        rows = cursor.fetchall()
    except Exception:
        used_fallback = True
        cursor.execute(f"SELECT embedding FROM {VEC_TABLE} WHERE paper_id = ?", (paper_id,))
        query_vector = cursor.fetchone()[0]
        cursor.execute(
            f"""
            SELECT v.paper_id, v.distance, p.title
            FROM {VEC_TABLE} v
            JOIN paper p ON p.id = v.paper_id
            WHERE v.embedding MATCH ?
              AND k = 6
            ORDER BY v.distance
            """,
            (query_vector,),
        )
        rows = cursor.fetchall()

    if used_fallback:
        print("(note: subquery-as-MATCH form failed; fetched embedding blob in Python instead)\n")

    rows = [r for r in rows if r[0] != paper_id][:5]

    for _, distance, title in rows:
        print(f"{distance:.4f}  {title}")


def main():
    db = connect(DB_PATH)

    if len(sys.argv) < 2:
        list_papers(db)
    else:
        paper_id = int(sys.argv[1])
        neighbors(db, paper_id)

    db.close()


if __name__ == "__main__":
    main()
