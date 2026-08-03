#!/usr/bin/env python3
"""Extract every paper that still needs it: the 2 'failed' library rows (re-run
at the raised 250k gate -> should flip to ok) + all explore papers with PDFs
(first-time extraction). Serial, fail-soft, idempotent. Reuses run_extract.py's
proven extract_and_persist AS-IS (now at MAX_INPUT_CHARS=250000).
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

from run_extract import FIELDS, MAX_INPUT_CHARS, extract_and_persist


def _select_targets(cur):
    """pdf_path non-null AND file on disk AND (not in extractions OR failed)."""
    cur.execute(
        """
        SELECT p.id, p.source, p.pdf_path
        FROM paper p
        LEFT JOIN extractions e ON e.paper_id = p.id
        WHERE p.pdf_path IS NOT NULL
          AND (e.paper_id IS NULL OR e.extract_status = 'failed')
        ORDER BY p.id
        """
    )
    rows = cur.fetchall()
    targets = [(pid, src, Path(pp)) for pid, src, pp in rows if Path(pp).exists()]
    missing = [(pid, src, pp) for pid, src, pp in rows if not Path(pp).exists()]
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
        return f"ok {stored}/4 verified{extra}"
    drop_str = ", ".join(f"{f}@{sc:.2f}" for f, sc in dropped)
    return f"partial: {stored} stored, {len(dropped)} dropped ({drop_str})"


async def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    # ---------- STEP 1 ----------
    print("=" * 90)
    print(f"STEP 1: target set (gate now MAX_INPUT_CHARS={MAX_INPUT_CHARS})")
    print("-" * 90)
    targets, missing = _select_targets(cur)
    lib = [t for t in targets if t[1] == "library"]
    exp = [t for t in targets if t[1] == "explore"]
    ids = {pid for pid, _, _ in targets}

    print(f"  total targets: {len(targets)}  (library={len(lib)}, explore={len(exp)})")
    print(f"  library 'failed' re-runs: {sorted(pid for pid, _, _ in lib)}")
    print(f"  ids 1 and 20 included: 1->{1 in ids}  20->{20 in ids}")
    if missing:
        print(f"  ({len(missing)} had a pdf_path that no longer exists on disk -- excluded)")
        for pid, src, pp in missing:
            print(f"      excluded id={pid} ({src}): {pp}")
    print()

    # ---------- STEP 2 ----------
    print("=" * 90)
    print("STEP 2: serial extract+persist run")
    print("-" * 90)
    for pid, src, path in targets:
        try:
            report = await extract_and_persist(db, path, pid)
            print(f"  id={pid:<3} {src:<7} {path.name:46.46} -> {report['status']:7} | {_summary_line(report)}")
        except Exception as e:
            print(f"  id={pid:<3} {src:<7} {path.name:46.46} -> ERROR (kept going): {type(e).__name__}: {e}")
    print()

    # ---------- STEP 3 ----------
    print("=" * 90)
    print("STEP 3: final readout")
    print("-" * 90)
    cur.execute("SELECT extract_status, COUNT(*) FROM extractions GROUP BY extract_status")
    dist = dict(cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM extractions")
    total = cur.fetchone()[0]
    print(f"  distribution: ok={dist.get('ok',0)}  partial={dist.get('partial',0)}  "
          f"failed={dist.get('failed',0)}  total={total}")
    print()

    for check_id in (1, 20):
        cur.execute("SELECT extract_status FROM extractions WHERE paper_id=?", (check_id,))
        row = cur.fetchone()
        st = row[0] if row else "(no row)"
        print(f"  library id={check_id}: extract_status={st}  {'<- now ok (over-length fix landed)' if st=='ok' else ''}")
    print()

    # Full dump of any partial/failed
    cols = ["paper_id", "extract_status"]
    for f in FIELDS:
        cols += [f"{f}_value", f"{f}_span", f"{f}_score"]
    cur.execute(
        f"SELECT {', '.join(cols)} FROM extractions WHERE extract_status != 'ok' ORDER BY paper_id"
    )
    non_ok = cur.fetchall()
    if not non_ok:
        print("  no partial/failed rows -- all extractions are ok")
    else:
        print(f"  full dump of {len(non_ok)} non-ok row(s):")
        for r in non_ok:
            d = dict(zip(cols, r))
            cur.execute("SELECT pdf_path FROM paper WHERE id=?", (d["paper_id"],))
            prow = cur.fetchone()
            fn = Path(prow[0]).name if prow and prow[0] else "?"
            print(f"  --- paper_id={d['paper_id']}  status={d['extract_status']}  {fn} ---")
            for f in FIELDS:
                print(f"      {f}: value={d[f'{f}_value']!r}  span={d[f'{f}_span']!r}  score={d[f'{f}_score']}")
    print()

    # Explore papers still without an extraction row
    cur.execute(
        """
        SELECT p.id, p.arxiv_id, p.pdf_path
        FROM paper p
        LEFT JOIN extractions e ON e.paper_id = p.id
        WHERE p.source='explore' AND e.paper_id IS NULL
        ORDER BY p.id
        """
    )
    no_row = cur.fetchall()
    if no_row:
        print(f"  explore papers still WITHOUT an extraction row ({len(no_row)}):")
        for pid, aid, pp in no_row:
            reason = "no PDF (parked)" if not pp else "has PDF but no row (unexpected)"
            print(f"      id={pid} arxiv={aid}: {reason}")
    print("=" * 90)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
