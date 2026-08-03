"""Read-only Obsidian vault routes.

Mirrors the {nodes, links, ...} response shape of /library/graph and
/explore/graph so the frontend graph pattern carries over. No endpoint here
writes to the vault -- the backend owns file access, in one direction only.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import VAULT_PATH
from backend.vault import CATEGORIES, build_graph, find_page, graph_stats

router = APIRouter()


def _resolve_vault() -> Path:
    """The configured vault directory, or a clean 503.

    Misconfiguration is an expected operational state (the path is per-machine
    and never hardcoded), so it gets an explicit, explanatory status -- never an
    unhandled exception surfacing as a 500.
    """
    if not VAULT_PATH:
        raise HTTPException(
            status_code=503,
            detail=(
                "CLIO_VAULT_PATH is not set. Point it at your Obsidian vault "
                "(see .env.example) and restart the backend."
            ),
        )
    path = Path(VAULT_PATH)
    if not path.is_dir():
        raise HTTPException(
            status_code=503,
            detail=f"CLIO_VAULT_PATH is set to '{VAULT_PATH}', which is not an existing directory.",
        )
    return path


@router.get("/vault/graph")
async def get_vault_graph():
    vault = _resolve_vault()
    graph = build_graph(vault)
    return {
        "nodes": graph["nodes"],
        "links": graph["links"],
        "categories": list(CATEGORIES),
        "stats": graph_stats(graph),
    }


@router.get("/vault/page/{stem}")
async def get_vault_page(stem: str):
    vault = _resolve_vault()
    page = find_page(vault, stem)
    if page is None:
        raise HTTPException(status_code=404, detail=f"No vault page with stem '{stem}'")
    return page
