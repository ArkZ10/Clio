#!/usr/bin/env python3
"""F3a SPIKE: read-only grounded extract + span verification.

Proves the extract shape and the >=0.90 span-grounding gate on a few library
PDFs BEFORE any persistence (F3b) or explore PDF-fetch (F1). Writes NOTHING to
the database. Throwaway proving script, not pipeline code.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

# extract routes to deepseek (TEMP) -- load .env so DEEPSEEK_API_KEY resolves,
# same pattern as the rerank/label CLIs.
dotenv.load_dotenv(ROOT / ".env")

import pymupdf4llm
from rapidfuzz import fuzz

import llm_switch
from backend.routing import resolve_stage

PDF_DIR = ROOT / "data" / "papers" / "pdfs"
MAX_INPUT_CHARS = 120_000
SPAN_THRESHOLD = 0.90
FIELDS = ["problem", "method", "result", "contribution"]

SYSTEM_PROMPT = """You are given the full markdown text of a research paper. Extract four fields:
problem, method, result, contribution.

For EACH field return an object with two keys:
  - "value": a concise 1-2 sentence synthesis of that field, in your own words.
  - "source_span": a quote copied VERBATIM, character-for-character, from the
    provided text, that most directly supports "value".

HARD RULES:
- source_span MUST be an exact copy from the text. Do NOT paraphrase, fix
  typos, fix spacing, translate, or summarize inside source_span.
- Keep source_span to one sentence or clause (roughly under 45 words), long
  enough to be a real, locatable quote.
- If the text does not support a field, set BOTH "value" and "source_span" to
  null. Never invent a quote. A null field is acceptable; a fabricated span is
  not.

Output STRICTLY a JSON object, no preamble, no markdown fences, shape:
{"problem":{"value":...,"source_span":...},
 "method":{"value":...,"source_span":...},
 "result":{"value":...,"source_span":...},
 "contribution":{"value":...,"source_span":...}}"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MD_CHARS_RE = re.compile(r"[#*`_>|]")
_WS_RE = re.compile(r"\s+")


def choose_pdfs() -> list[Path]:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    maskforge = next((p for p in pdfs if p.name == "maskforge_attack.pdf"), None)
    if maskforge is None:
        print("maskforge_attack.pdf ABSENT -- using first 5 alphabetically instead.")
        return pdfs[:5]
    others = [p for p in pdfs if p.name != "maskforge_attack.pdf"][:4]
    return [maskforge] + others


def normalize(s: str) -> str:
    s = s.lower()
    s = _MD_CHARS_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def verify_span(span, md_norm: str, md_raw: str):
    """Returns (status, score). status in {NULL, PASS, FAIL}. On FAIL also
    finds the closest ~len(span) window of md for display (attached separately)."""
    if span is None:
        return ("NULL", None, None)
    span_norm = normalize(span)
    if not span_norm:
        return ("FAIL", 0.0, "")
    score = fuzz.partial_ratio(span_norm, md_norm) / 100.0
    if score >= SPAN_THRESHOLD:
        return ("PASS", score, None)

    # Best-matching window for display: slide over md_norm at span length.
    best_window = _best_window(span_norm, md_norm)
    return ("FAIL", score, best_window)


def _best_window(span_norm: str, md_norm: str) -> str:
    """Find the md substring (~span length) with the highest partial_ratio."""
    w = len(span_norm)
    if w == 0 or w >= len(md_norm):
        return md_norm[:200]
    best_score = -1.0
    best = ""
    step = max(1, w // 4)
    for i in range(0, len(md_norm) - w + 1, step):
        window = md_norm[i:i + w]
        sc = fuzz.ratio(span_norm, window)
        if sc > best_score:
            best_score = sc
            best = window
    return best


def _extract_json(raw: str):
    text = _FENCE_RE.sub("", raw.strip()).strip()
    return json.loads(text)


async def process(path: Path):
    md = pymupdf4llm.to_markdown(str(path))

    if len(md) > MAX_INPUT_CHARS:
        print(f"SKIP {path.name}: text too long ({len(md)} chars), needs chunking design")
        return None

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": md},
    ]
    endpoint = resolve_stage("extract")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=2000
    )

    try:
        obj = _extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        print(f"PARSE FAIL {path.name}")
        print(f"  raw (first 500): {result.text[:500]!r}")
        return None

    md_norm = normalize(md)

    print(f"=== {path.name} ===")
    counts = {"PASS": 0, "NULL": 0, "FAIL": 0}
    fails = []
    for field in FIELDS:
        entry = obj.get(field) or {}
        value = entry.get("value")
        span = entry.get("source_span")
        status, score, window = verify_span(span, md_norm, md)
        counts[status] += 1

        if status == "NULL":
            verify_str = "NULL"
        elif status == "PASS":
            verify_str = f"PASS ({score:.2f})"
        else:
            verify_str = f"FAIL ({score:.2f})"
            fails.append((field, score))

        print(f"FIELD: {field}")
        print(f"  value      : {value if value is not None else 'NULL'}")
        print(f"  source_span: {span if span is not None else 'NULL'}")
        print(f"  verify     : {verify_str}")
        if status == "FAIL":
            print(f"  best match in text: \"{window[:200]}\"")
    print(f"fields: {counts['PASS']} pass / {counts['NULL']} null / {counts['FAIL']} FAIL")
    print()

    return {"file": path.name, "counts": counts, "fails": fails}


async def main():
    chosen = choose_pdfs()
    print("Chosen PDFs:")
    for p in chosen:
        print(f"  - {p.name}")
    print()

    results = []
    for path in chosen:
        r = await process(path)
        if r is not None:
            results.append(r)

    total_pass = sum(r["counts"]["PASS"] for r in results)
    total_null = sum(r["counts"]["NULL"] for r in results)
    total_fail = sum(r["counts"]["FAIL"] for r in results)
    total_fields = total_pass + total_null + total_fail

    print("=" * 70)
    print("FINAL SUMMARY")
    print("-" * 70)
    print(f"  papers evaluated: {len(results)}")
    print(f"  total fields evaluated: {total_fields}")
    print(f"  PASS: {total_pass}   NULL: {total_null}   FAIL: {total_fail}")
    print(f"\n  FAILS (the dangerous ones -- span did not ground >= {SPAN_THRESHOLD}):")
    any_fail = False
    for r in results:
        for field, score in r["fails"]:
            any_fail = True
            print(f"    {r['file']}:{field} ({score:.2f})")
    if not any_fail:
        print("    (none)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
