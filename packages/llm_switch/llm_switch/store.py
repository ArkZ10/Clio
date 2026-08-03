"""JSON-backed endpoint registry at ~/.llm_switch/endpoints.json.

Secret handling: a caller-supplied api_key is stored as one of three forms:
  - None                  -> no key (local endpoints)
  - "env:VARNAME" literal -> stored verbatim, NEVER resolved on disk
  - any other literal     -> encrypted via crypto.encrypt -> "enc:..."
resolve_api_key() is the only place a real secret value is produced, and it
is called at runtime only -- never during register/save.
"""
import json
import os
from pathlib import Path
from typing import Optional

from . import crypto
from .errors import LLMError

_STORE_PATH = Path(os.path.expanduser("~/.llm_switch/endpoints.json"))


def _default_data() -> dict:
    return {"endpoints": {}}


def load() -> dict:
    if not _STORE_PATH.exists():
        return _default_data()
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_data()
    if not isinstance(data, dict) or not isinstance(data.get("endpoints"), dict):
        return _default_data()
    return data


def save(data: dict) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _prepare_api_key(api_key: Optional[str]) -> Optional[str]:
    """Transform a caller-supplied api_key into its on-disk representation."""
    if api_key is None:
        return None
    if api_key.startswith("env:"):
        return api_key
    return crypto.encrypt(api_key)


def add_endpoint(
    name: str,
    base_url: str,
    api_key: Optional[str] = None,
    kind: str = "auto",
    default_model: Optional[str] = None,
) -> dict:
    data = load()
    record = {
        "base_url": base_url,
        "api_key": _prepare_api_key(api_key),
        "kind": kind,
        "default_model": default_model,
    }
    data["endpoints"][name] = record
    save(data)
    return record


def get_endpoint(name: str) -> Optional[dict]:
    return load()["endpoints"].get(name)


def list_endpoints() -> dict:
    return load()["endpoints"]


def remove_endpoint(name: str) -> bool:
    data = load()
    if name in data["endpoints"]:
        del data["endpoints"][name]
        save(data)
        return True
    return False


def resolve_api_key(record: dict) -> Optional[str]:
    """Resolve a stored api_key field to its real runtime secret. Call at
    request time only -- this is the one function that produces a plaintext
    secret in memory."""
    raw = record.get("api_key")
    if raw is None:
        return None
    if raw.startswith("env:"):
        varname = raw[len("env:"):]
        value = os.environ.get(varname)
        if value is None:
            raise LLMError(500, f"Environment variable {varname} is not set")
        return value
    if crypto.is_encrypted(raw):
        return crypto.decrypt(raw)
    return raw
