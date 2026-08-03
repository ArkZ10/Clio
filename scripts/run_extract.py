#!/usr/bin/env python3
"""F3b: extract grounded fields and PERSIST them to the `extractions` table.

Adds DB writes + a retry-and-flag handler for empty / stochastic-reasoning
responses on top of the F3a-proven extract shape and >=0.90 grounding gate.
Only the extractions table is written; paper is never touched.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

dotenv.load_dotenv(ROOT / ".env")

import pymupdf4llm

import llm_switch
from backend.config import DB_PATH
from backend.db import connect
from backend.routing import resolve_stage

# Reuse the F3a-proven pieces verbatim -- do not re-derive.
from spike_f3a_extract import (
    FIELDS,
    SYSTEM_PROMPT,
    _extract_json,
    choose_pdfs,
    normalize,
    verify_span,
)

# Production input gate, owned here (not inherited from the throwaway spike).
# Raised 120000 -> 250000 after the gate-raise experiment showed every paper in
# the corpus (max ~137k chars / ~49k input tokens) extracts clean with huge
# headroom; 250k keeps a wide margin while still guarding truly enormous inputs.
MAX_INPUT_CHARS = 250000
EXTRACT_MAX_TOKENS = 16000
EXTRACT_MODEL = "deepseek"  # the endpoint resolve_stage("extract") points at


def resolve_paper_id(cursor, path: Path):
    cursor.execute(
        "SELECT id FROM paper WHERE pdf_path = ?", (str(path.resolve()),)
    )
    row = cursor.fetchone()
    return row[0] if row else None


async def _call_extract(md: str):
    """One extract call. Returns parsed dict, or None if empty/unparseable."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": md},
    ]
    endpoint = resolve_stage("extract")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=EXTRACT_MAX_TOKENS
    )
    if not result.text.strip():
        return None
    try:
        return _extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        return None


def _empty_record(paper_id: int, status: str) -> dict:
    rec = {"paper_id": paper_id, "extract_status": status,
           "extract_model": EXTRACT_MODEL,
           "extracted_at": datetime.now(timezone.utc).isoformat()}
    for f in FIELDS:
        rec[f"{f}_value"] = None
        rec[f"{f}_span"] = None
        rec[f"{f}_score"] = None
    return rec


def _upsert(db, rec: dict):
    cols = ["paper_id"]
    for f in FIELDS:
        cols += [f"{f}_value", f"{f}_span", f"{f}_score"]
    cols += ["extract_status", "extract_model", "extracted_at"]
    placeholders = ", ".join("?" for _ in cols)
    values = [rec.get(c) for c in cols]
    db.execute(
        f"INSERT OR REPLACE INTO extractions ({', '.join(cols)}) VALUES ({placeholders})",
        values,
    )
    db.commit()


async def extract_and_persist(db, path: Path, paper_id: int) -> dict:
    md = pymupdf4llm.to_markdown(str(path))

    # (a) input budget -- fail loud, never silently truncate
    if len(md) > MAX_INPUT_CHARS:
        print(f"  FAILED (input too long): {len(md)} chars > {MAX_INPUT_CHARS}")
        rec = _empty_record(paper_id, "failed")
        _upsert(db, rec)
        return {"status": "failed", "fields": []}

    # (b)+(c) extract with one retry on empty/unparseable
    obj = await _call_extract(md)
    if obj is None:
        obj = await _call_extract(md)  # one fresh call, new reasoning length
        if obj is None:
            print(f"  FAILED after retry: {path.name}")
            rec = _empty_record(paper_id, "failed")
            _upsert(db, rec)
            return {"status": "failed", "fields": []}

    # (d) per-field grounding gate
    md_norm = normalize(md)
    rec = {"paper_id": paper_id, "extract_model": EXTRACT_MODEL,
           "extracted_at": datetime.now(timezone.utc).isoformat()}
    any_fail = False
    field_report = []

    for f in FIELDS:
        entry = obj.get(f) or {}
        value = entry.get("value")
        span = entry.get("source_span")
        status, score, _window = verify_span(span, md_norm, md)

        if status == "NULL":
            rec[f"{f}_value"] = value           # value as given (may be null)
            rec[f"{f}_span"] = None
            rec[f"{f}_score"] = None
            field_report.append((f, "null", value, None))
        elif status == "PASS":
            rec[f"{f}_value"] = value
            rec[f"{f}_span"] = span
            rec[f"{f}_score"] = score
            field_report.append((f, "stored", value, score))
        else:  # FAIL: span unverifiable -> drop value+span, keep failing score
            any_fail = True
            rec[f"{f}_value"] = None
            rec[f"{f}_span"] = None
            rec[f"{f}_score"] = score
            field_report.append((f, "dropped<0.90", value, score))

    # (e) status
    rec["extract_status"] = "partial" if any_fail else "ok"

    # (f) upsert
    _upsert(db, rec)
    return {"status": rec["extract_status"], "fields": field_report}


async def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    chosen = choose_pdfs()
    print("Papers to extract:")
    for p in chosen:
        print(f"  - {p.name}")
    print()

    written_ids = []
    for path in chosen:
        paper_id = resolve_paper_id(cur, path)
        print(f"=== {path.name} -> paper_id={paper_id} ===")
        if paper_id is None:
            print("  SKIP: no paper row maps to this pdf_path")
            print()
            continue

        report = await extract_and_persist(db, path, paper_id)
        written_ids.append(paper_id)
        print(f"  extract_status: {report['status']}")
        for f, disposition, value, score in report["fields"]:
            short = (value[:70] + "...") if isinstance(value, str) and len(value) > 70 else value
            sc = f"{score:.2f}" if isinstance(score, float) else "-"
            print(f"    {f:13} [{disposition:13}] score={sc}  {short!r}")
        print()

    # SELECT-back proof
    print("=" * 80)
    print("SELECT-BACK from extractions (proving the writes landed):")
    print("-" * 80)
    qmarks = ",".join("?" for _ in written_ids)
    cur.execute(
        f"SELECT paper_id, extract_status, "
        f"problem_score, method_score, result_score, contribution_score, "
        f"substr(problem_value,1,45), extract_model, extracted_at "
        f"FROM extractions WHERE paper_id IN ({qmarks}) ORDER BY paper_id",
        written_ids,
    )
    for r in cur.fetchall():
        print(f"  paper_id={r[0]}  status={r[1]}  scores(p/m/r/c)="
              f"{r[2]}/{r[3]}/{r[4]}/{r[5]}  model={r[7]}")
        print(f"      problem_value: {r[6]!r}")
        print(f"      extracted_at:  {r[8]}")
    print("=" * 80)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
