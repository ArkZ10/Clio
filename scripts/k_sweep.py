#!/usr/bin/env python3
"""Read-only sweep of kNN k values to compare graph density (hairball check).
Persists nothing -- build_knn_edges only selects, cluster_papers is pure.

Clustering must stay frozen across k (it never receives k, only the
embeddings) -- this script verifies that and flags loudly if it ever isn't,
which would mean edges are leaking into clustering.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect
from backend.graph.build import load_vectors
from backend.graph.knn import build_knn_edges
from backend.graph.cluster import cluster_papers

K_VALUES = [3, 4, 5, 6]


def main():
    db = connect(DB_PATH)
    paper_ids, X = load_vectors(db)
    n = len(paper_ids)
    max_edges = n * (n - 1) // 2

    rows = []
    label_arrays = []
    for k in K_VALUES:
        edges = build_knn_edges(db, paper_ids, X, k=k)
        labels = cluster_papers(X, min_cluster_size=2)
        label_arrays.append(np.asarray(labels))

        unique = sorted({int(l) for l in labels if l != -1})
        noise = int(sum(1 for l in labels if l == -1))
        rows.append((k, len(edges), len(unique), noise))

    db.close()

    # Frozen-clustering check: every label array must equal the first.
    frozen = all(np.array_equal(label_arrays[0], la) for la in label_arrays[1:])

    print("=" * 70)
    print(f"{n} nodes  |  max possible edges = {max_edges}")
    print("=" * 70)
    print(f"{'k':>3} | {'edges':>6} | {'% of max':>8} | {'clusters':>8} | {'unclustered':>11}")
    print("-" * 70)
    for k, e, c, noise in rows:
        pct = f"{100 * e / max_edges:.0f}%"
        print(f"{k:>3} | {e:>6} | {pct:>8} | {c:>8} | {noise:>11}")
    print("=" * 70)

    if frozen:
        c0 = rows[0][2]
        noise0 = rows[0][3]
        print(f"CLUSTERING FROZEN: identical across all k "
              f"({c0} clusters, {noise0} unclustered every row). "
              f"Edges do not leak into clustering.")
    else:
        print("!!! CLUSTERING CHANGED ACROSS k -- edges are leaking into "
              "clustering. This is a bug. STOP and investigate.")
    print("=" * 70)


if __name__ == "__main__":
    main()
