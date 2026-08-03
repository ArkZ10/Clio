#!/usr/bin/env python3
"""Force re-embed papers whose titles were fixed, comparing fresh vs stored
vector so we can REPORT whether each was actually stale or already current.

No timestamp exists on vec_bge_m3 to detect staleness automatically, so this
operates on the explicit list of papers whose titles were fixed this session.
The embed text is title+abstract, so the cosine between the freshly-computed
vector and the stored one tells us directly: ~1.0 = stored vector already
encodes the current title (current); notably < 1.0 = it encoded the old
garbled title (stale, now corrected).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect, insert_embedding
from backend.embedders.registry import get_embedder

# Titles fixed this session (garbled -> clean). Both were re-embedded at fix
# time, so they're expected to already be current -- the cosine proves it.
KNOWN_FIXED_IDS = [10, 22]


def main():
    embedder = get_embedder("bge-m3")
    db = connect(DB_PATH)
    cursor = db.cursor()

    rows = []
    for paper_id in KNOWN_FIXED_IDS:
        cursor.execute("SELECT title, abstract FROM paper WHERE id = ?", (paper_id,))
        r = cursor.fetchone()
        if r is None:
            print(f"id={paper_id}: NOT FOUND, skipping")
            continue
        title, abstract = r
        cursor.execute("SELECT embedding FROM vec_bge_m3 WHERE paper_id = ?", (paper_id,))
        vrow = cursor.fetchone()
        stored = np.frombuffer(vrow[0], dtype=np.float32) if vrow else None
        text = f"{title}\n{abstract}" if title else abstract
        rows.append((paper_id, title, text, stored))

    # One batched embed call for all candidates.
    fresh_vectors = embedder.embed([r[2] for r in rows])

    print("=" * 90)
    for (paper_id, title, _text, stored), fresh in zip(rows, fresh_vectors):
        if stored is not None:
            # both are L2-normalized, so cosine == dot product
            cosine = float(np.dot(fresh, stored))
            status = "already current" if cosine >= 0.9999 else "WAS STALE (now corrected)"
        else:
            cosine = float("nan")
            status = "had no stored vector (now embedded)"

        # Force-write the fresh vector (delete-then-insert; insert alone would
        # collide on the primary key).
        cursor.execute("DELETE FROM vec_bge_m3 WHERE paper_id = ?", (paper_id,))
        db.commit()
        insert_embedding(db, embedder.vec_table, paper_id, fresh)

        print(f"id={paper_id:<3} cosine(fresh,stored)={cosine:.6f}  [{status}]  {title[:55]}")
    print("=" * 90)

    db.close()


if __name__ == "__main__":
    main()
