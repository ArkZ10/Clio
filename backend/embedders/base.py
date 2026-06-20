from typing import Protocol
import numpy as np


class Embedder(Protocol):
    name: str          # 'bge-m3'
    dim: int           # 1024
    metric: str        # 'cosine'
    vec_table: str     # 'vec_bge_m3'

    def embed(self, texts: list[str]) -> np.ndarray: ...   # (len(texts), dim) float32
