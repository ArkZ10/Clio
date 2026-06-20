#!/usr/bin/env python3
"""Embed library papers (title+abstract) with BGE-M3 and store in vec_bge_m3."""
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

    cursor.execute("SELECT id, title, abstract, ingest_notes FROM paper WHERE source = 'library'")
    papers = cursor.fetchall()

    to_embed = []  # (id, text)
    already_embedded = 0
    skipped = 0

    for paper_id, title, abstract, ingest_notes in papers:
        if has_embedding(db, paper_id, embedder.vec_table):
            already_embedded += 1
            continue

        if abstract is None or not abstract.strip():
            new_notes_parts = [ingest_notes] if ingest_notes else []
            new_notes_parts.append("no abstract — not embedded")
            new_notes = " | ".join(new_notes_parts)
            cursor.execute(
                "UPDATE paper SET needs_review = 1, ingest_notes = ? WHERE id = ?",
                (new_notes, paper_id),
            )
            db.commit()
            cursor.execute("SELECT pdf_path FROM paper WHERE id = ?", (paper_id,))
            pdf_path = cursor.fetchone()[0]
            filename = Path(pdf_path).name if pdf_path else f"paper_id={paper_id}"
            print(f"SKIPPED (no abstract): {filename}")
            skipped += 1
            continue

        text = f"{title}\n{abstract}" if title else abstract
        to_embed.append((paper_id, text))

    embedded = 0
    if to_embed:
        ids = [p[0] for p in to_embed]
        texts = [p[1] for p in to_embed]
        vectors = embedder.embed(texts)

        for paper_id, vector in zip(ids, vectors):
            insert_embedding(db, embedder.vec_table, paper_id, vector)
            embedded += 1

    db.close()

    print(
        f"\n{embedded} embedded, {skipped} skipped (no abstract), "
        f"{already_embedded} already embedded"
    )


if __name__ == "__main__":
    main()
