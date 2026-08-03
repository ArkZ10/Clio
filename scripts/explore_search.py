#!/usr/bin/env python3
"""CLI: search arXiv for a topic, store/dedup results, print a readable report."""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.explore.cache import search_arxiv_cached
from backend.explore.store import (
    TAG_ALREADY_IN_EXPLORE,
    TAG_ALREADY_IN_LIBRARY,
    TAG_NEW_EXPLORE,
    store_explore_results,
)

TAG_LABELS = {
    TAG_NEW_EXPLORE: "[NEW EXPLORE]",
    TAG_ALREADY_IN_LIBRARY: "[ALREADY IN LIBRARY]",
    TAG_ALREADY_IN_EXPLORE: "[ALREADY IN EXPLORE]",
}


def brief(abstract: str, max_lines: int = 2, width: int = 100) -> str:
    wrapped = textwrap.wrap(abstract.strip().replace("\n", " "), width=width)
    return "\n    ".join(wrapped[:max_lines]) + ("..." if len(wrapped) > max_lines else "")


def main():
    if len(sys.argv) < 2:
        print("Usage: explore_search.py <topic>")
        sys.exit(1)

    topic = " ".join(sys.argv[1:])

    results, from_cache = search_arxiv_cached(topic, max_results=25)
    print(f"Query: {topic!r}  ({'served from cache' if from_cache else 'fetched from arXiv'})")
    print(f"{len(results)} result(s)")
    print()

    summary, tags = store_explore_results(results)

    for r, tag in zip(results, tags):
        print(f"{TAG_LABELS[tag]} {r.title}")
        print(f"    arXiv:{r.arxiv_id}")
        print(f"    {brief(r.abstract)}")
        print()

    print("=" * 80)
    print(
        f"fetched={summary['fetched']}  "
        f"inserted_explore={summary['inserted_explore']}  "
        f"already_in_library={summary['already_in_library']}  "
        f"already_in_explore={summary['already_in_explore']}"
    )


if __name__ == "__main__":
    main()
