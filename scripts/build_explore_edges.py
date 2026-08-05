#!/usr/bin/env python3
"""Computes + persists semantic kNN edges for the explore papers.
Backend/offline only -- no route, no UI. Idempotent, isolated from library.

Isolation: graph_edge has no source/exploration column, only `layer` (library
uses 'semantic'). A distinct value, EXPLORE_LAYER = 'semantic_explore_1',
makes explore edges invisible to library's `WHERE layer = 'semantic'` query
with no schema change.

Not a straight call to backend/graph/knn.py's build_knn_edges: vec_bge_m3 now
holds both library and explore vectors in one shared index, and that query has
no source filter, so it could pull library papers in as "neighbors". This
reuses its exact query shape and weight formula, but over-fetches and
post-filters down to explore-only ids before taking the top-k, without
touching backend/graph/knn.py.
"""
import sys
from pathlib import Path

import numpy as np
from sqlite_vec import serialize_float32

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

EXPLORE_LAYER = "semantic_explore_1"
K_DEFAULT = 4  # same as backend/graph/knn.py's K_DEFAULT


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


def build_explore_knn_edges(db, paper_ids, X, k=K_DEFAULT):
    """Same MATCH query, weight formula, and undirected dedupe as
    backend/graph/knn.py's build_knn_edges, but candidates are POST-FILTERED to
    explore paper_ids only -- vec_bge_m3 is shared with library, so an
    unfiltered MATCH could otherwise surface library neighbors."""
    n = len(paper_ids)
    if n < 2:
        return []
    explore_set = set(paper_ids)

    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM vec_bge_m3")
    total_vectors = cursor.fetchone()[0]
    # over-fetch: enough neighbors to guarantee k explore-only survivors even in
    # the worst case where every non-explore vector outranks every explore one.
    fetch_k = min(total_vectors, n + (total_vectors - n))  # == total_vectors

    edges = {}  # (src, dst) -> weight
    for i, paper_id in enumerate(paper_ids):
        query_vector = serialize_float32([float(v) for v in X[i]])
        cursor.execute(
            """
            SELECT paper_id, distance FROM vec_bge_m3
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (query_vector, fetch_k),
        )
        neighbors = cursor.fetchall()

        kept = 0
        for neighbor_id, distance in neighbors:
            if neighbor_id == paper_id:
                continue
            if neighbor_id not in explore_set:  # post-filter: explore-only
                continue
            weight = 1.0 - distance
            src, dst = min(paper_id, neighbor_id), max(paper_id, neighbor_id)
            key = (src, dst)
            if key not in edges:
                edges[key] = weight
            kept += 1
            if kept >= k:
                break

    return [(src, dst, weight) for (src, dst), weight in edges.items()]


def clear_explore_edges(db):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM graph_edge WHERE layer = ?", (EXPLORE_LAYER,))
    existing = cur.fetchone()[0]
    cur.execute("DELETE FROM graph_edge WHERE layer = ?", (EXPLORE_LAYER,))
    db.commit()
    return existing


def insert_edges(db, edges):
    cur = db.cursor()
    for src, dst, weight in edges:
        cur.execute(
            "INSERT INTO graph_edge (src_paper_id, dst_paper_id, layer, weight) "
            "VALUES (?, ?, ?, ?)",
            (src, dst, EXPLORE_LAYER, weight),
        )
    db.commit()


def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    # ================= STEP 0 =================
    print("=" * 90)
    print("STEP 0: inspect edge schema + isolation approach")
    print("-" * 90)
    schema = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_edge'"
    ).fetchone()[0]
    print(schema)
    print()
    print(f"Isolation approach: distinct layer value '{EXPLORE_LAYER}' "
          f"(no schema change). Library route filters WHERE layer='semantic' "
          f"(exact string match, confirmed in backend/routes/library.py:32) --")
    print(f"'{EXPLORE_LAYER}' != 'semantic', so it is invisible to that query.")
    print()

    explore_ids, X = load_explore_vectors(db)
    print(f"explore papers with a vec_bge_m3 vector: {len(explore_ids)}/49")

    # ================= STEP 1 =================
    print()
    print("=" * 90)
    print(f"STEP 1: build explore kNN edges (k={K_DEFAULT}, layer='{EXPLORE_LAYER}')")
    print("-" * 90)
    replaced = clear_explore_edges(db)
    print(f"idempotent clear: removed {replaced} pre-existing '{EXPLORE_LAYER}' edge(s)"
          f"{' (first run)' if replaced == 0 else ''}")

    edges = build_explore_knn_edges(db, explore_ids, X, k=K_DEFAULT)
    insert_edges(db, edges)
    print(f"built + inserted {len(edges)} explore-layer edges "
          f"(library 'semantic' edges untouched -- different layer, no DELETE issued against it)")

    # ================= STEP 2 =================
    print()
    print("=" * 90)
    print("STEP 2: verify (read-back, prove isolation)")
    print("-" * 90)

    explore_count = cur.execute(
        "SELECT COUNT(*) FROM graph_edge WHERE layer = ?", (EXPLORE_LAYER,)
    ).fetchone()[0]
    library_count = cur.execute(
        "SELECT COUNT(*) FROM graph_edge WHERE layer = 'semantic'"
    ).fetchone()[0]
    print(f"explore-layer ('{EXPLORE_LAYER}') edges: {explore_count}")
    print(f"library 'semantic' edges: {library_count}  "
          f"(expected UNCHANGED at 50) -> {'OK' if library_count == 50 else 'MISMATCH!!'}")
    assert library_count == 50, f"library edge count changed! now {library_count}"

    # cross-contamination checks
    bad_explore_edges = cur.execute(
        f"""
        SELECT COUNT(*) FROM graph_edge ge
        JOIN paper p ON p.id IN (ge.src_paper_id, ge.dst_paper_id)
        WHERE ge.layer = ? AND p.source = 'library'
        """,
        (EXPLORE_LAYER,),
    ).fetchone()[0]
    bad_library_edges = cur.execute(
        """
        SELECT COUNT(*) FROM graph_edge ge
        JOIN paper p ON p.id IN (ge.src_paper_id, ge.dst_paper_id)
        WHERE ge.layer = 'semantic' AND p.source = 'explore'
        """
    ).fetchone()[0]
    print(f"explore-layer edges referencing a LIBRARY paper_id: {bad_explore_edges}  "
          f"-> {'OK (0)' if bad_explore_edges == 0 else 'CONTAMINATION!!'}")
    print(f"library 'semantic' edges referencing an EXPLORE paper_id: {bad_library_edges}  "
          f"-> {'OK (0)' if bad_library_edges == 0 else 'CONTAMINATION!!'}")
    assert bad_explore_edges == 0
    assert bad_library_edges == 0

    # coherence eyeball: 5 sample explore edges with titles
    print()
    print("5 sample explore edges (title A --weight--> title B):")
    sample = cur.execute(
        f"""
        SELECT ge.src_paper_id, ge.dst_paper_id, ge.weight,
               pa.title, pb.title
        FROM graph_edge ge
        JOIN paper pa ON pa.id = ge.src_paper_id
        JOIN paper pb ON pb.id = ge.dst_paper_id
        WHERE ge.layer = ?
        ORDER BY ge.weight DESC
        LIMIT 5
        """,
        (EXPLORE_LAYER,),
    ).fetchall()
    for src, dst, weight, ta, tb in sample:
        ta_s = (ta or "")[:55]
        tb_s = (tb or "")[:55]
        print(f"  [{src}] {ta_s}  --{weight:.3f}-->  [{dst}] {tb_s}")

    # isolated node count
    connected = set()
    for src, dst, *_ in cur.execute(
        "SELECT src_paper_id, dst_paper_id FROM graph_edge WHERE layer = ?",
        (EXPLORE_LAYER,),
    ).fetchall():
        connected.add(src)
        connected.add(dst)
    isolated = sorted(set(explore_ids) - connected)
    print()
    print(f"explore papers with >=1 edge: {len(connected)}/{len(explore_ids)}")
    print(f"isolated (0-edge) explore papers: {len(isolated)}  ids={isolated}")

    print("=" * 90)
    db.close()


if __name__ == "__main__":
    main()
