#!/usr/bin/env python3
"""Throwaway experiment: do the over-length papers extract cleanly at a raised
input gate (200k) + larger output budget (16k)? Decides whether chunking must
exist. Read-only, writes nothing. Reuses run_extract.py's prompt, call
pattern, and verify_span via spike_f3a_extract.
"""
import asyncio
import json
import sys
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

# Same prompt / verify / parse as the production path (run_extract imports these).
from spike_f3a_extract import (
    FIELDS,
    SYSTEM_PROMPT,
    _extract_json,
    normalize,
    verify_span,
)

TARGET_IDS = [25, 27, 46, 1, 20]
RAISED_INPUT_GATE = 200_000      # was 120_000
RAISED_MAX_TOKENS = 16_000       # was 8_000
CEILING = 15_500                 # output >= this => likely truncated
TOK_PER_CHAR = 1 / 3.7


async def _call(md: str):
    """One extract call at the raised budget. Returns (obj|None, usage|{})."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": md},
    ]
    endpoint = resolve_stage("extract")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=RAISED_MAX_TOKENS
    )
    usage = result.usage or {}
    if not result.text.strip():
        return None, usage
    try:
        return _extract_json(result.text), usage
    except (json.JSONDecodeError, ValueError):
        return "PARSE_FAIL", usage


def _usage_split(usage: dict):
    inp = usage.get("prompt_tokens")
    out = usage.get("completion_tokens")
    reasoning = None
    det = usage.get("completion_tokens_details")
    if isinstance(det, dict):
        reasoning = det.get("reasoning_tokens")
    return inp, out, reasoning


async def process(path: Path, paper_id: int) -> dict:
    md = pymupdf4llm.to_markdown(str(path))
    chars = len(md)
    est_tok = int(chars * TOK_PER_CHAR)
    print(f"=== id={paper_id}  {path.name} ===")
    print(f"  chars={chars}  est_input_tokens~{est_tok}  (raised gate {RAISED_INPUT_GATE}: accepted)")

    obj, usage = await _call(md)
    if obj is None or obj == "PARSE_FAIL":
        obj, usage = await _call(md)  # retry once

    inp, out, reasoning = _usage_split(usage)
    truncated = isinstance(out, int) and out >= CEILING
    if reasoning is not None:
        print(f"  usage: input={inp} output={out} reasoning={reasoning}")
    else:
        print(f"  usage: input={inp} output={out} reasoning=not-exposed | raw={usage}")
    print(f"  ceiling check: output {out} {'>= ' + str(CEILING) + ' -> LIKELY TRUNCATED' if truncated else '< ' + str(CEILING) + ' (ok)'}")

    # Verdict precedence: structural failure first, then grounding.
    if obj is None:
        print("  result: EMPTY after retry")
        verdict = "NEEDS-CHUNKING"
        why = "empty after retry"
    elif obj == "PARSE_FAIL":
        print("  result: PARSE FAIL after retry")
        verdict = "NEEDS-CHUNKING"
        why = "parse fail"
    else:
        md_norm = normalize(md)
        any_fail = False
        for f in FIELDS:
            entry = obj.get(f) or {}
            span = entry.get("source_span")
            status, score, _ = verify_span(span, md_norm, md)
            score_str = f"{score:.2f}" if isinstance(score, float) else "-"
            print(f"    {f:13} -> {status} ({score_str})")
            if status == "FAIL":
                any_fail = True
        if truncated:
            verdict = "NEEDS-CHUNKING"
            why = "output hit ceiling (truncated)"
        elif any_fail:
            verdict = "GROUNDING-ISSUE"
            why = ">=1 span scored <0.90"
        else:
            verdict = "EXTRACTS-CLEAN"
            why = "valid JSON, all spans grounded, not truncated"

    print(f"  VERDICT: {verdict}  ({why})")
    print()
    return {"id": paper_id, "chars": chars, "est_tok": est_tok,
            "out": out, "reasoning": reasoning, "truncated": truncated,
            "verdict": verdict}


async def main():
    db = connect(DB_PATH)
    cur = db.cursor()

    print("Resolving target paths:")
    targets = []
    for pid in TARGET_IDS:
        cur.execute("SELECT pdf_path FROM paper WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row or not row[0] or not Path(row[0]).exists():
            print(f"  id={pid}: MISSING/UNREADABLE pdf_path ({row[0] if row else None}) -- skipping")
            continue
        print(f"  id={pid}: {row[0]}")
        targets.append((pid, Path(row[0])))
    db.close()
    print()

    results = []
    for pid, path in targets:
        results.append(await process(path, pid))

    # Final table
    print("=" * 100)
    print("FINAL READOUT")
    print("-" * 100)
    print(f"{'id':>4} | {'chars':>7} | {'est_in_tok':>10} | {'out_tok':>7} | {'reason_tok':>10} | {'ceiling?':>8} | verdict")
    print("-" * 100)
    for r in results:
        ceil = "TRUNC" if r["truncated"] else "ok"
        rt = r["reasoning"] if r["reasoning"] is not None else "-"
        print(f"{r['id']:>4} | {r['chars']:>7} | {r['est_tok']:>10} | {str(r['out']):>7} | {str(rt):>10} | {ceil:>8} | {r['verdict']}")
    print("=" * 100)

    clean = [r for r in results if r["verdict"] == "EXTRACTS-CLEAN"]
    not_clean = [r for r in results if r["verdict"] != "EXTRACTS-CLEAN"]

    if results and len(clean) == len(results):
        max_clean = max(r["chars"] for r in clean)
        # recommend a gate above the largest clean paper with margin
        suggested = ((max_clean // 10000) + 2) * 10000
        print(f"GATE-RAISE SUFFICIENT: all {len(results)} extract clean -> raise gate to {suggested}, chunking NOT needed")
        print(f"  (largest clean paper was {max_clean} chars; {suggested} adds margin)")
    else:
        forced = [(r["id"], r["verdict"]) for r in not_clean]
        clean_max = max((r["chars"] for r in clean), default=None)
        print(f"PARTIAL: {len(clean)}/{len(results)} clean; chunking needed only for ids "
              f"{[i for i, _ in forced]}")
        for i, v in forced:
            print(f"  id={i} forced by: {v}")
        if clean_max is not None:
            suggested = ((clean_max // 10000) + 2) * 10000
            print(f"  largest CLEAN paper: {clean_max} chars -> a safe production gate is ~{suggested} "
                  f"(papers above that route to chunking)")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
