from .bge_m3 import BgeM3Embedder

_EMBEDDERS = {
    "bge-m3": BgeM3Embedder,
}

_instances = {}


def get_embedder(name: str):
    if name not in _EMBEDDERS:
        raise ValueError(f"Unknown embedder: {name}. Available: {list(_EMBEDDERS)}")
    if name not in _instances:
        _instances[name] = _EMBEDDERS[name]()
    return _instances[name]
