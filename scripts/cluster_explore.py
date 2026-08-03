#!/usr/bin/env python3
"""Cluster the source='explore' papers with the EXACT v1 method + params
(HDBSCAN min_cluster_size=2 via backend.graph.cluster.cluster_papers), over the
EXPLORE set ONLY -- library vectors are not loaded into this pass.

Assignments are stored the same way v1 stores them (cluster + paper_cluster),
but tagged with a non-NULL exploration_id sentinel so they stay separable from
library clusters (which use exploration_id IS NULL). Idempotent: re-running
clears the prior explore clusters first. -1 = HDBSCAN noise (reported, not
forced into a cluster).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect
from backend.graph.cluster import cluster_papers

# No `exploration` table exists; exploration_id is a nullable int column on
# `cluster` (library = NULL). A fixed sentinel tags the explore set and keeps it
# separable from library without touching the library (NULL) clusters.
EXPLORE_EXPLORATION_ID = 1
MIN_CLUSTER_SIZE = 2  # identical to v1 build_graph default


def load_explore_vectors(db):
    cur = db.cursor()
    cur.execute(
        """
        SELECT v.paper_id, v.embedding
        FROM vec_bge_m3 v JOIN paper p ON p.id = v.paper_id
        WHERE p.source = 'explore'
        ORDER BY v.paper_id
        """
    )
    rows = cur.fetchall()
    if not rows:
        return [], np.zeros((0, 1024), dtype=np.float32)
    paper_ids = [r[0] for r in rows]
    X = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return paper_ids, X


def clear_prior_explore_clusters(db):
    cur = db.cursor()
    cur.execute(
        "DELETE FROM paper_cluster WHERE cluster_id IN "
        "(SELECT id FROM cluster WHERE exploration_id = ?)",
        (EXPLORE_EXPLORATION_ID,),
    )
    cur.execute(
        "DELETE FROM cluster WHERE exploration_id = ?", (EXPLORE_EXPLORATION_ID,)
    )
    db.commit()


def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    paper_ids, X = load_explore_vectors(db)
    titles = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT id, title FROM paper WHERE source='explore'"
        ).fetchall()
    }

    print("=" * 90)
    print("STEP 2: cluster explore set (HDBSCAN, min_cluster_size="
          f"{MIN_CLUSTER_SIZE}, explore-only)")
    print("-" * 90)
    print(f"  explore vectors loaded: {len(paper_ids)}")
    if len(paper_ids) == 0:
        print("  no explore vectors -- run embed_explore.py first.")
        db.close()
        return

    # SAME function, SAME params as v1.
    labels = cluster_papers(X, min_cluster_size=MIN_CLUSTER_SIZE)
    labels = [int(l) for l in labels]

    # Idempotent rewrite, tagged to the explore set.
    clear_prior_explore_clusters(db)
    unique = sorted({l for l in labels if l != -1})
    label_to_cluster_id = {}
    for lab in unique:
        cur.execute(
            "INSERT INTO cluster (exploration_id, label, summary) VALUES (?, ?, NULL)",
            (EXPLORE_EXPLORATION_ID, f"Cluster {lab}"),
        )
        label_to_cluster_id[lab] = cur.lastrowid
    db.commit()

    noise_ids = []
    members = {lab: [] for lab in unique}
    for pid, lab in zip(paper_ids, labels):
        if lab == -1:
            noise_ids.append(pid)
            continue
        cur.execute(
            "INSERT INTO paper_cluster (paper_id, cluster_id) VALUES (?, ?)",
            (pid, label_to_cluster_id[lab]),
        )
        members[lab].append(pid)
    db.commit()

    print(f"  clusters formed: {len(unique)}   noise(-1): {len(noise_ids)}")
    print(f"  assignments stored: cluster.exploration_id={EXPLORE_EXPLORATION_ID}, "
          f"paper_cluster rows={sum(len(m) for m in members.values())}")
    print()

    # ---------------- STEP 3: readout gate ----------------
    print("=" * 90)
    print("STEP 3: cluster readout (coherence gate)")
    print("-" * 90)
    sizes = []
    for lab in unique:
        m = members[lab]
        sizes.append(len(m))
        cid = label_to_cluster_id[lab]
        print(f"\n  CLUSTER {lab}  (db cluster.id={cid})  size={len(m)}")
        for pid in m:
            print(f"      [{pid}] {titles.get(pid, '?')}")

    print()
    print("-" * 90)
    print(f"  clusters formed : {len(unique)}")
    print(f"  NOISE / unclustered (label -1): {len(noise_ids)}")
    for pid in noise_ids:
        print(f"      [{pid}] {titles.get(pid, '?')}")
    if sizes:
        arr = sorted(sizes)
        med = arr[len(arr) // 2] if len(arr) % 2 else (arr[len(arr)//2 - 1] + arr[len(arr)//2]) / 2
        print(f"  cluster size distribution: min={min(sizes)}  median={med}  max={max(sizes)}")
    else:
        print("  cluster size distribution: (no clusters)")
    print("=" * 90)
    db.close()


if __name__ == "__main__":
    main()
