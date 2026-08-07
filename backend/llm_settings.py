"""Safe, read-only view over llm_switch's endpoint registry for the Settings
page. Resolves whether a key is set and how, without ever exposing the key
itself -- a literal key is Fernet-encrypted at rest, and even decrypted, it
must never leave this process toward the browser.
"""
from __future__ import annotations

import llm_switch
from llm_switch import store as llm_store


def _key_info(raw_key: str | None) -> dict:
    if raw_key is None:
        return {"has_key": False, "key_source": None, "key_env_var": None}
    if raw_key.startswith("env:"):
        return {"has_key": True, "key_source": "env", "key_env_var": raw_key[len("env:"):]}
    return {"has_key": True, "key_source": "stored", "key_env_var": None}


def list_endpoints() -> list[dict]:
    out = []
    for endpoint in llm_switch.list_endpoints():
        record = llm_store.get_endpoint(endpoint.name) or {}
        out.append(
            {
                "name": endpoint.name,
                "base_url": endpoint.base_url,
                "kind": endpoint.kind,
                "default_model": endpoint.default_model,
                "is_local": endpoint.is_local,
                "provider": endpoint.provider,
                **_key_info(record.get("api_key")),
            }
        )
    return out
