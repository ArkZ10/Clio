"""Day-level cache for arXiv queries, keyed by (normalized query, max_results).

arXiv's own guidance: results for a query don't meaningfully change within a
day, so don't re-hit the API for a query already fetched today -- serve from
cache instead.
"""
import json
from dataclasses import asdict
from datetime import date

from backend.config import EXPLORE_CACHE_PATH

from .retrieve import ArxivResult, search_arxiv


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _cache_key(query: str, max_results: int) -> str:
    return f"{_normalize_query(query)}|{max_results}"


def _load_cache() -> dict:
    if not EXPLORE_CACHE_PATH.exists():
        return {}
    try:
        with open(EXPLORE_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    EXPLORE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPLORE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def search_arxiv_cached(query: str, max_results: int = 25) -> tuple[list[ArxivResult], bool]:
    """Same results as search_arxiv(), but served from an on-disk cache if
    this (query, max_results) pair was already fetched today. Returns
    (results, from_cache)."""
    key = _cache_key(query, max_results)
    cache = _load_cache()
    entry = cache.get(key)

    if entry is not None and entry.get("date") == date.today().isoformat():
        return [ArxivResult(**r) for r in entry["results"]], True

    results = search_arxiv(query, max_results=max_results)
    cache[key] = {
        "date": date.today().isoformat(),
        "results": [asdict(r) for r in results],
    }
    _save_cache(cache)
    return results, False
