#!/usr/bin/env python3
"""Backfills the paper_text cache for every paper whose pdf_path resolves on
disk, then proves it's a real cache (repeat-call hit, byte-for-byte fidelity
vs a fresh parse, stale-detection). Reuses backend.paper_text.get_or_parse_markdown.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect
from backend.paper_text import (
    PARSER_VERSION,
    _cache_valid,
    get_or_parse_markdown,
    parse_markdown,
)


def _targets(db):
    rows = db.execute(
        "SELECT id, pdf_path FROM paper WHERE pdf_path IS NOT NULL ORDER BY id"
    ).fetchall()
    resolved, unresolved = [], []
    for pid, pp in rows:
        (resolved if Path(pp).exists() else unresolved).append((pid, pp))
    return resolved, unresolved


def step2_backfill(db):
    print("=" * 78)
    print(f"STEP 2: backfill (current parser = {PARSER_VERSION})")
    print("-" * 78)
    resolved, unresolved = _targets(db)

    total_chars = 0
    hits = misses = 0
    for pid, pp in resolved:
        md, status = get_or_parse_markdown(pid, pp, db)
        total_chars += len(md)
        if status == "HIT":
            hits += 1
        else:
            misses += 1
        print(f"  id={pid:<3} -> {status:4} -> {len(md):>7} chars")

    print("-" * 78)
    print(f"  total cached: {len(resolved)}  (HIT={hits}, MISS={misses})")
    print(f"  total chars : {total_chars:,}")
    if unresolved:
        print(f"  unresolved pdf_path ({len(unresolved)}) -- skipped + logged:")
        for pid, pp in unresolved:
            print(f"      id={pid}: {pp}")
    else:
        print("  unresolved pdf_path: none")
    print("=" * 78)
    return [pid for pid, _ in resolved]


def step3_prove(db, cached_ids):
    print()
    print("=" * 78)
    print("STEP 3: prove it is a REAL cache")
    print("-" * 78)

    # 3a -- repeat-call HIT returning identical text
    sample = cached_ids[:3]
    print(f"3a. repeat-call HIT on ids {sample}:")
    for pid in sample:
        pp = db.execute("SELECT pdf_path FROM paper WHERE id=?", (pid,)).fetchone()[0]
        md1, s1 = get_or_parse_markdown(pid, pp, db)
        md2, s2 = get_or_parse_markdown(pid, pp, db)
        identical = (len(md1) == len(md2)) and (md1 == md2)
        print(f"    id={pid}: call1={s1} call2={s2}  "
              f"len={len(md1)}=={len(md2)}  identical={identical}")
    print()

    # 3b -- fidelity: cached text == fresh direct parse, character-for-character
    fid_id = cached_ids[0]
    pp = db.execute("SELECT pdf_path FROM paper WHERE id=?", (fid_id,)).fetchone()[0]
    cached_md = db.execute(
        "SELECT markdown FROM paper_text WHERE paper_id=?", (fid_id,)
    ).fetchone()[0]
    fresh_md = parse_markdown(pp)            # bypass the cache entirely
    fidelity = cached_md == fresh_md
    print("3b. fidelity vs a fresh direct parse (cache bypassed):")
    print(f"    id={fid_id}: cached_len={len(cached_md)} fresh_len={len(fresh_md)}")
    print(f"    CACHE FIDELITY: {fid_id} cached==fresh -> {fidelity}")
    print()

    # 3c -- stale detection logic (in-memory only; DB untouched, no re-parse)
    stale_id = cached_ids[0]
    real_tag = db.execute(
        "SELECT parser FROM paper_text WHERE paper_id=?", (stale_id,)
    ).fetchone()[0]
    fake_tag = "pymupdf4llm-0.0.0-fake"
    print("3c. stale-detection logic (in-memory, no write, no re-parse):")
    print(f"    current parser tag : {PARSER_VERSION}")
    print(f"    stored tag for id={stale_id}: {real_tag} -> _cache_valid={_cache_valid(real_tag)} (HIT)")
    print(f"    simulated stale tag : {fake_tag} -> _cache_valid={_cache_valid(fake_tag)} (would be MISS -> re-parse)")
    print("=" * 78)


def main():
    db = connect(DB_PATH)
    cached_ids = step2_backfill(db)
    step3_prove(db, cached_ids)
    db.close()


if __name__ == "__main__":
    main()
