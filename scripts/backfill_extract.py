#!/usr/bin/env python3
"""F3b BACKFILL: extract+persist for the remaining LIBRARY papers not yet in
`extractions`, plus a re-write idempotency check and a status-distribution dump.

Reuses run_extract.py's extract_and_persist AS-IS -- no new extraction,
verification, or persistence logic. Explore papers (no PDFs) are excluded.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

# Reuse F3b's proven path verbatim.
from run_extract import FIELDS, extract_and_persist, resolve_paper_id


def _select_backfill_set(cur):
    """library papers with a real on-disk pdf_path NOT already in extractions."""
    cur.execute(
        """
        SELECT p.id, p.pdf_path
        FROM paper p
        WHERE p.source = 'library'
          AND p.pdf_path IS NOT NULL
          AND p.id NOT IN (SELECT paper_id FROM extractions)
        ORDER BY p.id
        """
    )
    rows = cur.fetchall()
    # filter to pdf_paths that actually resolve to a file on disk
    targets = [(pid, Path(pp)) for pid, pp in rows if Path(pp).exists()]
    missing = [(pid, pp) for pid, pp in rows if not Path(pp).exists()]
    return targets, missing


def _summary_line(report: dict) -> str:
    status = report["status"]
    fields = report["fields"]
    if status == "failed":
        return "failed: empty/unparseable after retry (or input too long)"
    stored = sum(1 for _, d, _, _ in fields if d == "stored")
    nulls = sum(1 for _, d, _, _ in fields if d == "null")
    dropped = [(f, sc) for f, d, _, sc in fields if d == "dropped<0.90"]
    if status == "ok":
        extra = f", {nulls} null" if nulls else ""
        return f"ok: {stored}/4 verified{extra}"
    # partial
    drop_str = ", ".join(f"{f}@{sc:.2f}" for f, sc in dropped)
    return f"partial: {stored} stored, {len(dropped)} dropped ({drop_str})"


async def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    # ---------- STEP 0 ----------
    print("=" * 80)
    print("STEP 0: backfill target set")
    print("-" * 80)
    targets, missing = _select_backfill_set(cur)

    cur.execute("SELECT COUNT(*) FROM paper WHERE source='library'")
    total_lib = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM extractions e "
        "JOIN paper p ON p.id = e.paper_id WHERE p.source='library'"
    )
    already = cur.fetchone()[0]

    if missing:
        print(f"  ({len(missing)} library paper(s) have a pdf_path that does NOT exist on disk -- excluded)")
        for pid, pp in missing:
            print(f"    excluded id={pid}: {pp}")

    print(f"  backfill set: {len(targets)} paper(s)")
    for pid, path in targets:
        print(f"    id={pid:<3} {path.name}")
    print()
    print(f"  arithmetic: already={already}  to-do={len(targets)}  total_library={total_lib}"
          f"   ({already} + {len(targets)} = {already + len(targets)})")
    print()

    # ---------- STEP 1 ----------
    print("=" * 80)
    print("STEP 1: backfill run")
    print("-" * 80)
    if not targets:
        print("  nothing to backfill")
    else:
        for pid, path in targets:
            try:
                report = await extract_and_persist(db, path, pid)
                print(f"  id={pid:<3} {path.name:48.48} -> {report['status']:7} | {_summary_line(report)}")
            except Exception as e:  # keep the batch going on any single failure
                print(f"  id={pid:<3} {path.name:48.48} -> ERROR (kept going): {type(e).__name__}: {e}")
    print()

    # ---------- STEP 2 ----------
    print("=" * 80)
    print("STEP 2: idempotency (re-write) check on paper_id=6")
    print("-" * 80)
    idem_id = 6
    cur.execute("SELECT pdf_path FROM paper WHERE id = ?", (idem_id,))
    row = cur.fetchone()
    if row is None or not row[0] or not Path(row[0]).exists():
        print(f"  paper_id={idem_id} has no usable pdf; skipping idempotency check")
    else:
        cur.execute("SELECT COUNT(*), MAX(extracted_at) FROM extractions WHERE paper_id=?", (idem_id,))
        before_count, before_ts = cur.fetchone()
        await extract_and_persist(db, Path(row[0]), idem_id)
        cur.execute("SELECT COUNT(*), MAX(extracted_at) FROM extractions WHERE paper_id=?", (idem_id,))
        after_count, after_ts = cur.fetchone()
        print(f"  idempotency: {before_count} row before, {after_count} row after, "
              f"timestamp updated {before_ts} -> {after_ts}")
    print()

    # ---------- STEP 3 ----------
    print("=" * 80)
    print("STEP 3: status distribution + non-ok dump")
    print("-" * 80)
    cur.execute("SELECT extract_status, COUNT(*) FROM extractions GROUP BY extract_status")
    dist = dict(cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM extractions")
    total = cur.fetchone()[0]
    print(f"  ok={dist.get('ok',0)}  partial={dist.get('partial',0)}  failed={dist.get('failed',0)}  total={total}")
    print()

    select_cols = ["paper_id", "extract_status"]
    for f in FIELDS:
        select_cols += [f"{f}_value", f"{f}_span", f"{f}_score"]
    cur.execute(
        f"SELECT {', '.join(select_cols)} FROM extractions WHERE extract_status != 'ok' ORDER BY paper_id"
    )
    non_ok = cur.fetchall()
    if not non_ok:
        print("  all rows ok -- no edge cases triggered")
    else:
        for r in non_ok:
            d = dict(zip(select_cols, r))
            cur.execute("SELECT pdf_path FROM paper WHERE id=?", (d["paper_id"],))
            prow = cur.fetchone()
            fn = Path(prow[0]).name if prow and prow[0] else "?"
            print(f"  --- paper_id={d['paper_id']}  status={d['extract_status']}  {fn} ---")
            for f in FIELDS:
                print(f"      {f}:")
                print(f"        value: {d[f'{f}_value']!r}")
                print(f"        span : {d[f'{f}_span']!r}")
                print(f"        score: {d[f'{f}_score']}")
    print("=" * 80)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
