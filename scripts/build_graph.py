#!/usr/bin/env python3
"""Build the library graph (kNN edges + HDBSCAN clusters) and print a report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect
from backend.graph.build import build_graph


def main():
    result = build_graph()

    n = result["nodes"]
    edges = result["edges"]
    c = result["clusters"]
    noise = result["noise"]

    print(f"{n} nodes, {len(edges)} edges, {c} clusters, {noise} unclustered")

    if not edges:
        return

    db = connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("SELECT id, title FROM paper")
    titles = {row[0]: row[1] for row in cursor.fetchall()}
    db.close()

    sorted_edges = sorted(edges, key=lambda e: e[2], reverse=True)

    print()
    for src, dst, weight in sorted_edges:
        title_a = (titles.get(src, "") or "")[:40]
        title_b = (titles.get(dst, "") or "")[:40]
        print(f"{weight:.3f}  {title_a:40}  --  {title_b:40}")


if __name__ == "__main__":
    main()
