"""HDBSCAN clustering over BGE-M3 embeddings."""
from sklearn.cluster import HDBSCAN


def cluster_papers(X, min_cluster_size=2):
    """
    Run HDBSCAN on the embedding matrix X (N, dim).
    Vectors are unit-normalized (Step 3), so euclidean distance is monotonic
    with cosine distance -- the default euclidean metric is fine here.
    Returns an array of int labels, length N. -1 = noise (unclustered).
    """
    if len(X) == 0:
        return []
    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, copy=False)
    return clusterer.fit_predict(X)
