"""Build kNN edges over BGE-M3 embeddings from vec_bge_m3."""
from sqlite_vec import serialize_float32

K_DEFAULT = 4


def build_knn_edges(db, paper_ids, X, k=K_DEFAULT):
    """
    For each paper, find its k nearest neighbors (excluding itself) in vec_bge_m3.
    Returns deduped undirected edges as a list of (src, dst, weight), src < dst.
    Weight = 1.0 - cosine_distance (higher = more similar).
    """
    n = len(paper_ids)
    effective_k = min(k, n - 1)
    if effective_k <= 0:
        return []

    cursor = db.cursor()
    edges = {}  # (src, dst) -> weight

    for i, paper_id in enumerate(paper_ids):
        query_vector = serialize_float32([float(v) for v in X[i]])

        # Fetch k+1: the query paper itself is always included (distance ~0)
        cursor.execute(
            """
            SELECT paper_id, distance FROM vec_bge_m3
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (query_vector, effective_k + 1),
        )
        neighbors = cursor.fetchall()

        for neighbor_id, distance in neighbors:
            if neighbor_id == paper_id:
                continue
            weight = 1.0 - distance
            src, dst = min(paper_id, neighbor_id), max(paper_id, neighbor_id)
            key = (src, dst)
            if key not in edges:
                edges[key] = weight

    return [(src, dst, weight) for (src, dst), weight in edges.items()]
