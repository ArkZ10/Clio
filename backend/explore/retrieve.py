"""arXiv retrieval. I/O with arXiv only -- no DB writes here (see store.py)."""
import re
from dataclasses import dataclass, field

import arxiv

_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


@dataclass
class ArxivResult:
    arxiv_id: str  # version-stripped, e.g. "2503.02130" -- stable dedup key
    title: str
    abstract: str
    authors: list[str]
    year: int | None
    categories: list[str]
    pdf_url: str | None


def _strip_version(short_id: str) -> str:
    """"2503.02130v2" -> "2503.02130". Dedup must key on the paper, not the
    revision -- a later version of a paper already in the library/explore
    set must still match it, not insert as new."""
    return _VERSION_SUFFIX_RE.sub("", short_id)


def search_arxiv(query: str, max_results: int = 25) -> list[ArxivResult]:
    """Retrieval only. Callable in a loop -- Level-2 query expansion will
    call this repeatedly with different queries later."""
    client = arxiv.Client(delay_seconds=3, num_retries=3)
    search = arxiv.Search(query=query, max_results=max_results)

    results = []
    for r in client.results(search):
        results.append(
            ArxivResult(
                arxiv_id=_strip_version(r.get_short_id()),
                title=r.title,
                abstract=r.summary,
                authors=[a.name for a in r.authors],
                year=r.published.year if r.published else None,
                categories=list(r.categories),
                pdf_url=r.pdf_url,
            )
        )
    return results
