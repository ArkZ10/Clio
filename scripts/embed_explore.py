#!/usr/bin/env python3
"""Embeds source='explore' papers the same way as library: BGE-M3, title+abstract
input, stored in vec_bge_m3 keyed to paper.id. Idempotent. Explore vectors
share the index with library but stay separable via paper.source; library
vectors aren't touched. Input construction matches embed_library.py exactly:
    text = f"{title}\\n{abstract}" if title else abstract
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect, has_embedding, insert_embedding
from backend.embedders.registry import get_embedder


def main():
    embedder = get_embedder("bge-m3")
    db = connect(DB_PATH)
    cursor = db.cursor()

    cursor.execute(
        "SELECT id, title, abstract FROM paper WHERE source = 'explore' ORDER BY id"
    )
    papers = cursor.fetchall()

    to_embed = []          # (id, text)
    already_embedded = 0
    skipped = []           # (id, reason)

    for paper_id, title, abstract in papers:
        # (a) idempotent skip
        if has_embedding(db, paper_id, embedder.vec_table):
            already_embedded += 1
            print(f"  SKIP (already embedded): id={paper_id}")
            continue

        # required field present? (all 49 confirmed non-null in Step 0, but guard)
        if abstract is None or not abstract.strip():
            skipped.append((paper_id, "no abstract"))
            print(f"  SKIP (no abstract): id={paper_id}")
            continue

        # (b) EXACT v1 input construction
        text = f"{title}\n{abstract}" if title else abstract
        to_embed.append((paper_id, text))

    # (c) same BGE-M3 path, same vec table
    embedded = 0
    if to_embed:
        ids = [p[0] for p in to_embed]
        texts = [p[1] for p in to_embed]
        vectors = embedder.embed(texts)
        for paper_id, vector in zip(ids, vectors):
            insert_embedding(db, embedder.vec_table, paper_id, vector)
            embedded += 1

    db.close()

    print()
    print("=" * 70)
    print("STEP 1: embed explore")
    print("-" * 70)
    print(f"  embedder        : {embedder.name} (dim={embedder.dim}, table={embedder.vec_table})")
    print(f"  explore papers  : {len(papers)}")
    print(f"  embedded        : {embedded}")
    print(f"  skipped (already): {already_embedded}")
    print(f"  failed/skipped  : {len(skipped)}  {skipped if skipped else ''}")
    print("=" * 70)


if __name__ == "__main__":
    main()
