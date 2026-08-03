"""Persist arXiv results into the shared `paper` table, deduped by arxiv_id.

library is sticky: an existing library paper is never modified or duplicated,
even if it shows up again in an explore search. That's the useful signal --
"you've already read this" -- not something to overwrite.
"""
import json

from backend.config import DB_PATH
from backend.db import connect, init_db

from .retrieve import ArxivResult

TAG_NEW_EXPLORE = "new_explore"
TAG_ALREADY_IN_LIBRARY = "already_in_library"
TAG_ALREADY_IN_EXPLORE = "already_in_explore"


def store_explore_results(results: list[ArxivResult]) -> tuple[dict, list[str]]:
    """Returns (summary, tags) -- tags is parallel to `results`, one of
    TAG_NEW_EXPLORE / TAG_ALREADY_IN_LIBRARY / TAG_ALREADY_IN_EXPLORE per
    result, for the caller to print per-paper detail."""
    init_db(DB_PATH)
    db = connect(DB_PATH)
    cursor = db.cursor()

    summary = {
        "fetched": len(results),
        "inserted_explore": 0,
        "already_in_library": 0,
        "already_in_explore": 0,
    }
    tags = []

    for r in results:
        cursor.execute(
            "SELECT source FROM paper WHERE arxiv_id = ?", (r.arxiv_id,)
        )
        row = cursor.fetchone()

        if row is not None:
            existing_source = row[0]
            if existing_source == "library":
                summary["already_in_library"] += 1
                tags.append(TAG_ALREADY_IN_LIBRARY)
            else:
                summary["already_in_explore"] += 1
                tags.append(TAG_ALREADY_IN_EXPLORE)
            continue

        cursor.execute(
            """INSERT INTO paper
               (title, abstract, source, authors, year, categories, arxiv_id,
                pdf_path, needs_review)
               VALUES (?, ?, 'explore', ?, ?, ?, ?, NULL, 0)""",
            (
                r.title,
                r.abstract,
                json.dumps(r.authors),
                r.year,
                json.dumps(r.categories),
                r.arxiv_id,
            ),
        )
        summary["inserted_explore"] += 1
        tags.append(TAG_NEW_EXPLORE)

    db.commit()
    db.close()
    return summary, tags
