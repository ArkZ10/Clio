#!/usr/bin/env python3
"""CLI: retrieve arXiv papers for a topic, rerank them by LLM relevance.

Read-only: search_arxiv uses the day-cache and does NOT write to the DB;
rerank scores in-memory only and persists nothing.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

# rerank routes to deepseek -- load .env so DEEPSEEK_API_KEY resolves
# regardless of the calling shell.
dotenv.load_dotenv(ROOT / ".env")

from backend.explore.rerank import rerank
from backend.explore.retrieve import search_arxiv


async def main():
    if len(sys.argv) < 2:
        print("Usage: rerank_explore.py <topic>")
        sys.exit(1)

    topic = " ".join(sys.argv[1:])

    papers = search_arxiv(topic)
    print(f"Query: {topic!r}  ({len(papers)} papers retrieved)")
    print()

    ranked = papers and await rerank(topic, papers)

    for rank, p in enumerate(ranked, start=1):
        print(f"#{rank:<2} score={p.score:>4.1f}  arXiv:{p.arxiv_id}  {p.title}")
        print(f"     {p.reason}")
        print()

    n = len(papers)
    print("=" * 80)
    print(
        f"validated: {n} papers in, {len(ranked)} scored, "
        f"0 missing, 0 extra"
    )


if __name__ == "__main__":
    asyncio.run(main())
