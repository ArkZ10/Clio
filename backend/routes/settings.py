"""Settings: llm_switch's endpoint registry + per-stage routing, for the
web UI's Settings page. Key values are never returned -- see
backend/llm_settings.py.
"""
import llm_switch
from fastapi import APIRouter, HTTPException
from llm_switch import store as llm_store
from pydantic import BaseModel

from backend import llm_settings, routing, routing_store

router = APIRouter()

STAGES = ("chat", "cluster_label", "rerank", "extract", "synthesis")


class CreateEndpointRequest(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    kind: str = "auto"
    default_model: str | None = None


@router.get("/settings/endpoints")
async def get_endpoints():
    return {"endpoints": llm_settings.list_endpoints()}


@router.post("/settings/endpoints")
async def create_endpoint(req: CreateEndpointRequest):
    """Registers a new endpoint, or updates one if `name` already exists --
    llm_switch's registry keys on name, so re-posting an existing name is
    how you edit it. Leaving api_key blank on an edit keeps the existing key
    rather than clearing it -- and it's restored by patching the stored
    record directly after, not by re-running it through llm_switch's key
    preparation, which would double-encrypt an already-encrypted value."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must not be empty")
    base_url = req.base_url.strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url must not be empty")
    if req.kind not in ("auto", "local", "api"):
        raise HTTPException(status_code=400, detail="kind must be one of: auto, local, api")

    existing = llm_store.get_endpoint(name)
    llm_switch.register_endpoint(
        name,
        base_url,
        api_key=req.api_key or None,
        kind=req.kind,
        default_model=req.default_model or None,
    )
    if not req.api_key and existing is not None and existing.get("api_key") is not None:
        data = llm_store.load()
        data["endpoints"][name]["api_key"] = existing["api_key"]
        llm_store.save(data)
    return {"ok": True}


@router.delete("/settings/endpoints/{name}")
async def delete_endpoint(name: str):
    if not llm_switch.remove_endpoint(name):
        raise HTTPException(status_code=404, detail=f"No endpoint named '{name}'")
    return {"ok": True}


@router.get("/settings/routing")
async def get_routing():
    overrides = routing_store.list_overrides()
    return {
        "routing": [
            {
                "stage": stage,
                "endpoint_name": overrides.get(stage, routing.DEFAULT_ROUTES[stage]),
                "default_endpoint_name": routing.DEFAULT_ROUTES[stage],
                "is_override": stage in overrides,
            }
            for stage in STAGES
        ]
    }


class SetRoutingRequest(BaseModel):
    endpoint_name: str


@router.put("/settings/routing/{stage}")
async def put_routing(stage: str, req: SetRoutingRequest):
    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
    if llm_switch.get_endpoint(req.endpoint_name) is None:
        raise HTTPException(
            status_code=400, detail=f"No endpoint named '{req.endpoint_name}'"
        )
    routing_store.set_override(stage, req.endpoint_name)
    return {"ok": True}


@router.delete("/settings/routing/{stage}")
async def reset_routing(stage: str):
    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
    routing_store.clear_override(stage)
    return {"ok": True}
