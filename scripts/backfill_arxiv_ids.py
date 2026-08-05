#!/usr/bin/env python3
"""Backfill arxiv_id on library papers, gated on abstract agreement (not
title): search arXiv by title, write the candidate's arxiv_id only if the
normalized abstracts match >= MATCH_THRESHOLD. A wrong id is worse than a
missing one.
"""
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import arxiv

from backend.config import DB_PATH
from backend.db import connect

MATCH_THRESHOLD = 0.90
MAX_CANDIDATES = 5

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_VERSION_RE = re.compile(r"v\d+$")


def normalize_abstract(s: str | None) -> str:
    """lowercase, strip all whitespace and non-alphanumeric -- collapses PDF
    line-wrap hyphenation ('of-\\nfering' -> 'offering'), LaTeX, punctuation."""
    if not s:
        return ""
    return _NON_ALNUM_RE.sub("", s.lower())


def containment_ratio(a: str, b: str) -> float:
    """Fraction of the SHORTER normalized abstract that matches the longer.
    Robust to one side carrying extra trailing junk (our PDF extraction
    sometimes appends figure/caption text after the real abstract)."""
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    sm = difflib.SequenceMatcher(None, shorter, longer)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(shorter)


def strip_version(short_id: str) -> str:
    return _VERSION_RE.sub("", short_id)


def main():
    db = connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, title, abstract FROM paper "
        "WHERE source='library' AND arxiv_id IS NULL ORDER BY id"
    )
    targets = cursor.fetchall()

    client = arxiv.Client(delay_seconds=3, num_retries=3)

    wrote = []      # (id, title, arxiv_id, ratio)
    skipped = []    # (id, title, best_ratio, closest_id, closest_title, reason)
    removed_dups = []  # (library_id, explore_id, arxiv_id)

    for paper_id, title, abstract in targets:
        norm_stored = normalize_abstract(abstract)
        if not norm_stored:
            skipped.append((paper_id, title, 0.0, None, None, "no stored abstract"))
            continue

        search = arxiv.Search(query=title, max_results=MAX_CANDIDATES)
        best_ratio = 0.0
        best_id = None
        best_title = None
        for r in client.results(search):
            cand_id = strip_version(r.get_short_id())
            ratio = containment_ratio(norm_stored, normalize_abstract(r.summary))
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = cand_id
                best_title = r.title

        if best_ratio >= MATCH_THRESHOLD and best_id is not None:
            # Collision handling: the abstract gate has CONFIRMED this paper ==
            # best_id, so any other row already holding best_id is the same
            # paper. If it's an explore row, it's a dup that slipped through
            # dedup (this library paper had NULL arxiv_id at search time) ->
            # delete it. If it's another library row, something is wrong -> skip.
            cursor.execute(
                "SELECT id, source FROM paper WHERE arxiv_id = ?", (best_id,)
            )
            collision = cursor.fetchone()
            if collision is not None:
                coll_id, coll_source = collision
                if coll_source == "library":
                    skipped.append(
                        (paper_id, title, best_ratio, best_id, best_title,
                         f"arxiv_id already on library row {coll_id}")
                    )
                    continue
                cursor.execute("DELETE FROM paper WHERE id = ?", (coll_id,))
                removed_dups.append((paper_id, coll_id, best_id))

            cursor.execute(
                "UPDATE paper SET arxiv_id = ? WHERE id = ?", (best_id, paper_id)
            )
            db.commit()
            wrote.append((paper_id, title, best_id, best_ratio))
        else:
            skipped.append(
                (paper_id, title, best_ratio, best_id, best_title, "below threshold")
            )

    db.close()

    print("=" * 90)
    print(f"WROTE ({len(wrote)}):")
    for pid, title, aid, ratio in wrote:
        print(f"  id={pid:<3} ratio={ratio:.3f}  arXiv:{aid}  {title[:55]}")

    if removed_dups:
        print()
        print(f"REMOVED EXPLORE DUPLICATES ({len(removed_dups)}):")
        for lib_id, exp_id, aid in removed_dups:
            print(f"  library id={lib_id} verified == explore id={exp_id} (arXiv:{aid}) -> deleted explore row")

    print()
    print(f"SKIPPED / LEFT NULL ({len(skipped)}):")
    for pid, title, best_ratio, cid, ctitle, reason in skipped:
        print(f"  id={pid:<3} best_ratio={best_ratio:.3f}  [{reason}]  {title[:50]}")
        if cid:
            print(f"         closest: arXiv:{cid}  {(ctitle or '')[:60]}")

    print("=" * 90)


if __name__ == "__main__":
    main()
