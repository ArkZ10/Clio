import numpy as np


class BgeM3Embedder:
    name = "bge-m3"
    dim = 1024
    metric = "cosine"
    vec_table = "vec_bge_m3"

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer("BAAI/bge-m3", device=device)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=8,
            show_progress_bar=True,
        )
        return embeddings.astype(np.float32)
