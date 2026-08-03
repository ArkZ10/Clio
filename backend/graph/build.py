"""Orchestrator: load BGE-M3 vectors, build kNN edges, cluster, persist."""
import numpy as np

from backend.config import DB_PATH
from backend.db import connect, init_db
from .knn import build_knn_edges, K_DEFAULT
from .cluster import cluster_papers


def load_vectors(db):
    cursor = db.cursor()
    cursor.execute("SELECT paper_id, embedding FROM vec_bge_m3 ORDER BY paper_id")
    rows = cursor.fetchall()
    paper_ids = [row[0] for row in rows]
    if not rows:
        return [], np.zeros((0, 1024), dtype=np.float32)
    vectors = [np.frombuffer(row[1], dtype=np.float32) for row in rows]
    X = np.stack(vectors)
    return paper_ids, X


def clear_library_graph(db):
    """Idempotent rebuild: wipe prior library (non-exploration) graph data."""
    cursor = db.cursor()
    cursor.execute("DELETE FROM graph_edge WHERE layer = 'semantic'")
    cursor.execute(
        "DELETE FROM paper_cluster WHERE cluster_id IN "
        "(SELECT id FROM cluster WHERE exploration_id IS NULL)"
    )
    cursor.execute("DELETE FROM cluster WHERE exploration_id IS NULL")
    db.commit()


def build_graph(k=K_DEFAULT, min_cluster_size=2):
    init_db(DB_PATH)
    db = connect(DB_PATH)

    paper_ids, X = load_vectors(db)
    n = len(paper_ids)

    clear_library_graph(db)

    if n == 0:
        db.close()
        return {"nodes": 0, "edges": [], "clusters": 0, "noise": 0}

    edges = build_knn_edges(db, paper_ids, X, k=k)

    cursor = db.cursor()
    for src, dst, weight in edges:
        cursor.execute(
            "INSERT INTO graph_edge (src_paper_id, dst_paper_id, layer, weight) "
            "VALUES (?, ?, 'semantic', ?)",
            (src, dst, weight),
        )
    db.commit()

    labels = cluster_papers(X, min_cluster_size=min_cluster_size)

    unique_labels = sorted({int(label) for label in labels if label != -1})
    label_to_cluster_id = {}
    for label in unique_labels:
        cursor.execute(
            "INSERT INTO cluster (exploration_id, label, summary) VALUES (NULL, ?, NULL)",
            (f"Cluster {label}",),
        )
        label_to_cluster_id[label] = cursor.lastrowid
    db.commit()

    noise_count = 0
    for paper_id, label in zip(paper_ids, labels):
        label = int(label)
        if label == -1:
            noise_count += 1
            continue
        cursor.execute(
            "INSERT INTO paper_cluster (paper_id, cluster_id) VALUES (?, ?)",
            (paper_id, label_to_cluster_id[label]),
        )
    db.commit()

    db.close()

    return {
        "nodes": n,
        "edges": edges,
        "clusters": len(unique_labels),
        "noise": noise_count,
    }
