#!/usr/bin/env python3
"""Concurrent orchestration around the EXISTING extract+verify+persist path.

Orchestration only -- extraction, verify_span, the prompt, retry, and the upsert
SQL are reused from run_extract.py UNCHANGED. The slow part (LLM call + span
verification) runs concurrently under a Semaphore; DB writes are serialized by
using a SINGLE shared sqlite connection (single writer => no lock contention),
which fits run_extract's existing pattern (extract_and_persist writes internally
via the passed connection, and that write is a synchronous no-await upsert).
"""
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

dotenv.load_dotenv(ROOT / ".env")

import llm_switch
from backend.config import DB_PATH
from backend.db import connect
from run_extract import FIELDS, extract_and_persist

CONCURRENCY = 5            # conservative; DeepSeek rate limits unknown. Tune later.
MAX_429_RETRIES = 3        # exponential backoff per paper on rate-limit


class RunStats:
    def __init__(self):
        self.rate_limit_hits = 0
        self.db_lock_errors = 0
        self.errors = []  # (paper_id, repr)


async def _extract_one(db, path, paper_id, sem, stats):
    """One paper: bounded by the semaphore, 429-backoff, fail-soft. The DB write
    happens inside extract_and_persist on the shared connection."""
    async with sem:
        for attempt in range(MAX_429_RETRIES):
            try:
                return await extract_and_persist(db, path, paper_id)
            except llm_switch.LLMError as e:
                if getattr(e, "status_code", None) == 429 and attempt < MAX_429_RETRIES - 1:
                    stats.rate_limit_hits += 1
                    backoff = 2 ** attempt
                    print(f"    [429] id={paper_id} attempt {attempt+1} -> backoff {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                stats.errors.append((paper_id, f"LLMError {getattr(e,'status_code','?')}"))
                print(f"    [FAIL kept going] id={paper_id}: {e}")
                return None
            except sqlite3.OperationalError as e:
                # would indicate a write-serialization problem -- count it loudly
                stats.db_lock_errors += 1
                stats.errors.append((paper_id, f"OperationalError: {e}"))
                print(f"    [DB ERROR] id={paper_id}: {e}")
                return None
            except Exception as e:  # any other failure: log, continue the batch
                stats.errors.append((paper_id, f"{type(e).__name__}: {e}"))
                print(f"    [FAIL kept going] id={paper_id}: {type(e).__name__}: {e}")
                return None


async def run_concurrent(db, targets, concurrency=CONCURRENCY):
    """targets: list of (paper_id, Path). Returns (results, stats)."""
    sem = asyncio.Semaphore(concurrency)
    stats = RunStats()
    coros = [_extract_one(db, path, pid, sem, stats) for pid, path in targets]
    results = await asyncio.gather(*coros)
    return results, stats


async def run_serial(db, targets):
    """Same work, one at a time (for the timing baseline)."""
    stats = RunStats()
    results = []
    for pid, path in targets:
        try:
            results.append(await extract_and_persist(db, path, pid))
        except sqlite3.OperationalError as e:
            stats.db_lock_errors += 1
            results.append(None)
        except Exception as e:
            stats.errors.append((pid, f"{type(e).__name__}: {e}"))
            results.append(None)
    return results, stats


# --------------------------------------------------------------------------
# Step 2/3: validate on already-extracted explore papers (idempotent upsert).
# --------------------------------------------------------------------------

def _pick_targets(cur, n=10):
    cur.execute(
        """
        SELECT p.id, p.pdf_path
        FROM paper p JOIN extractions e ON e.paper_id = p.id
        WHERE p.source='explore' AND e.extract_status='ok' AND p.pdf_path IS NOT NULL
        ORDER BY p.id LIMIT ?
        """,
        (n,),
    )
    return [(pid, Path(pp)) for pid, pp in cur.fetchall()]


def _snapshot(cur, ids):
    cols = ["paper_id", "extract_status", "extracted_at"]
    for f in FIELDS:
        cols += [f"{f}_score"]
    qmarks = ",".join("?" for _ in ids)
    cur.execute(
        f"SELECT {', '.join(cols)} FROM extractions WHERE paper_id IN ({qmarks}) ORDER BY paper_id",
        ids,
    )
    return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def _row_count(cur, ids):
    qmarks = ",".join("?" for _ in ids)
    cur.execute(f"SELECT COUNT(*) FROM extractions WHERE paper_id IN ({qmarks})", ids)
    return cur.fetchone()[0]


async def main():
    db = connect(DB_PATH)
    db.execute("PRAGMA busy_timeout=30000")  # defensive; single conn shouldn't ever wait
    cur = db.cursor()

    targets = _pick_targets(cur, 10)
    ids = [pid for pid, _ in targets]
    print("=" * 80)
    print(f"Validation targets (first 10 explore 'ok' rows): {ids}")
    print(f"rows for these ids BEFORE: {_row_count(cur, ids)}")
    before = _snapshot(cur, ids)
    print()

    # ---- concurrent run ----
    print(f"--- CONCURRENT run (CONCURRENCY={CONCURRENCY}) ---")
    t0 = time.perf_counter()
    _, cstats = await run_concurrent(db, targets, CONCURRENCY)
    concurrent_s = time.perf_counter() - t0
    print(f"  concurrent wall-clock: {concurrent_s:.1f}s")
    print(f"  429 hits: {cstats.rate_limit_hits}  db-lock errors: {cstats.db_lock_errors}")
    print()

    # ---- serial run (same 10) ----
    print("--- SERIAL run (same 10, one at a time) ---")
    t0 = time.perf_counter()
    _, sstats = await run_serial(db, targets)
    serial_s = time.perf_counter() - t0
    print(f"  serial wall-clock: {serial_s:.1f}s")
    print(f"  db-lock errors: {sstats.db_lock_errors}")
    print()

    # ---- integrity ----
    after_count = _row_count(cur, ids)
    after = _snapshot(cur, ids)
    well_formed = all(
        after[i]["extract_status"] in ("ok", "partial", "failed") for i in ids if i in after
    )

    print("=" * 80)
    print("STEP 3 READOUT")
    print("-" * 80)
    print(f"  approach: async-native llm_switch.call under asyncio.gather + Semaphore")
    print(f"            (no to_thread); writes serialized via SINGLE shared connection")
    print(f"  CONCURRENCY: {CONCURRENCY}")
    print(f"  serial time   : {serial_s:.1f}s")
    print(f"  concurrent time: {concurrent_s:.1f}s")
    speedup = serial_s / concurrent_s if concurrent_s else float('nan')
    print(f"  speedup factor : {speedup:.2f}x")
    print(f"  rows for the 10 ids: before=10 after={after_count}  "
          f"-> {'NO DUPLICATES' if after_count == 10 else 'DUPLICATE/LOSS!'}")
    print(f"  rows well-formed (status in ok/partial/failed): {well_formed}")
    print(f"  db-lock errors (concurrent): {cstats.db_lock_errors}  (serial): {sstats.db_lock_errors}  -> must be 0")
    print(f"  429 rate-limit hits: {cstats.rate_limit_hits}"
          f"{' (recovered via backoff)' if cstats.rate_limit_hits and not cstats.errors else ''}")
    if cstats.errors or sstats.errors:
        print(f"  non-fatal errors logged: {cstats.errors + sstats.errors}")
    # status sanity: show before/after status per id (structure, not exact text)
    print("  per-id status (before -> after), score columns present:")
    for i in ids:
        b = before.get(i, {})
        a = after.get(i, {})
        print(f"    id={i}: {b.get('extract_status')} -> {a.get('extract_status')}  "
              f"scores={[a.get(f'{f}_score') for f in FIELDS]}")
    print("=" * 80)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
