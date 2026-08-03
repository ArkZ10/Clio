"""llm_switch: a swappable local/cloud LLM endpoint registry + call layer."""
from dataclasses import dataclass
from typing import Optional

from . import detect, store
from .errors import LLMError

__all__ = [
    "Endpoint",
    "register_endpoint",
    "list_endpoints",
    "get_endpoint",
    "remove_endpoint",
    "resolve_api_key",
    "LLMError",
    "call",
    "stream",
    "CallResult",
]


@dataclass
class Endpoint:
    name: str
    base_url: str
    kind: str
    default_model: Optional[str]
    is_local: bool
    provider: str


def _to_endpoint(name: str, record: dict) -> Endpoint:
    base_url = record.get("base_url", "")
    kind = record.get("kind", "auto")
    return Endpoint(
        name=name,
        base_url=base_url,
        kind=kind,
        default_model=record.get("default_model"),
        is_local=detect.is_local(base_url, kind),
        provider=detect.detect_provider(base_url),
    )


def register_endpoint(
    name: str,
    base_url: str,
    api_key: Optional[str] = None,
    kind: str = "auto",
    default_model: Optional[str] = None,
) -> Endpoint:
    record = store.add_endpoint(
        name, base_url, api_key=api_key, kind=kind, default_model=default_model
    )
    return _to_endpoint(name, record)


def list_endpoints() -> list[Endpoint]:
    return [_to_endpoint(name, record) for name, record in store.list_endpoints().items()]


def get_endpoint(name: str) -> Optional[Endpoint]:
    record = store.get_endpoint(name)
    if record is None:
        return None
    return _to_endpoint(name, record)


def remove_endpoint(name: str) -> bool:
    return store.remove_endpoint(name)


def resolve_api_key(name: str) -> Optional[str]:
    record = store.get_endpoint(name)
    if record is None:
        raise LLMError(404, f"Endpoint '{name}' not found")
    return store.resolve_api_key(record)


# Imported last: client.py does `from . import get_endpoint, resolve_api_key`,
# which requires those names to already exist in this module's namespace.
from .client import call, stream, CallResult  # noqa: E402
