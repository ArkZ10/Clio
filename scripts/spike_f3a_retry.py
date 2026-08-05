#!/usr/bin/env python3
"""Narrow diagnostic: was DeepSeek's empty response on long papers output-
budget starvation (fixable via max_tokens) or input-size failure (needs
chunking)? Plus a token split readout and proving the gate's fail path.

Read-only, writes nothing. Reuses the original spike's helpers.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf4llm

import llm_switch
from backend.routing import resolve_stage

# Reuse the original spike's helpers / prompt verbatim -- do not re-derive.
from spike_f3a_extract import (
    FIELDS,
    MAX_INPUT_CHARS,
    SPAN_THRESHOLD,
    SYSTEM_PROMPT,
    _extract_json,
    normalize,
    verify_span,
)
from spike_f3a_extract import PDF_DIR

RETRY_MAX_TOKENS = 8000  # was 2000
CEILING_WARN = 7900      # output_tokens >= this => likely still truncated

FABRICATED_SPAN = (
    "Our method achieves a 47% reduction in sampling steps on ImageNet-512."
)


def resolve_targets() -> list[Path]:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    targets = []
    for needle in ("Flow", "Improving"):
        match = next((p for p in pdfs if needle.lower() in p.name.lower()), None)
        if match is None:
            print(f"  (could not resolve a PDF matching {needle!r})")
        else:
            targets.append(match)
    return targets


def _usage_token_split(usage: dict):
    """DeepSeek (OpenAI-compatible) usage shape:
      prompt_tokens, completion_tokens, total_tokens,
      completion_tokens_details: {reasoning_tokens: N}
    Returns (input_tokens, output_tokens, reasoning_tokens_or_None)."""
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    reasoning = None
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
    return input_tokens, output_tokens, reasoning


async def process(path: Path) -> dict:
    md = pymupdf4llm.to_markdown(str(path))
    md_norm = normalize(md)

    print(f"=== {path.name} ===")
    print(f"  input chars: {len(md)}")

    if len(md) > MAX_INPUT_CHARS:
        print(f"  SKIP: too long, {len(md)} chars")
        return {"file": path.name, "classification": "INPUT-SIZE",
                "reason": "tripped 120k input gate", "md": md, "md_norm": md_norm,
                "pass_spans": []}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": md},
    ]
    endpoint = resolve_stage("extract")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=RETRY_MAX_TOKENS
    )

    # --- token split ---
    usage = result.usage or {}
    in_tok, out_tok, reasoning_tok = _usage_token_split(usage)
    print(f"  tokens: input={in_tok}  output={out_tok}", end="")
    if reasoning_tok is not None:
        print(f"  reasoning={reasoning_tok}")
    else:
        print("  reasoning tokens: not exposed")
        print(f"    raw usage: {usage}")
    if isinstance(out_tok, int):
        if out_tok >= CEILING_WARN:
            print(f"  ceiling: output {out_tok} >= {CEILING_WARN} -> LIKELY STILL TRUNCATED")
        else:
            print(f"  ceiling: output {out_tok} finished comfortably under {RETRY_MAX_TOKENS}")

    # --- parse + verify ---
    if not result.text.strip():
        print("  EMPTY RESPONSE (result.text is blank)")
        return {"file": path.name, "classification": "INPUT-SIZE",
                "reason": "empty response even at max_tokens=8000",
                "md": md, "md_norm": md_norm, "pass_spans": []}

    try:
        obj = _extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        print("  PARSE FAIL")
        print(f"    raw (first 500): {result.text[:500]!r}")
        return {"file": path.name, "classification": "INPUT-SIZE",
                "reason": "parse fail even at max_tokens=8000",
                "md": md, "md_norm": md_norm, "pass_spans": []}

    counts = {"PASS": 0, "NULL": 0, "FAIL": 0}
    pass_spans = []
    for field in FIELDS:
        entry = obj.get(field) or {}
        value = entry.get("value")
        span = entry.get("source_span")
        status, score, window = verify_span(span, md_norm, md)
        counts[status] += 1
        if status == "PASS":
            pass_spans.append(span)

        verify_str = ("NULL" if status == "NULL"
                      else f"{status} ({score:.2f})")
        print(f"  FIELD: {field}")
        print(f"    value      : {value if value is not None else 'NULL'}")
        print(f"    source_span: {span if span is not None else 'NULL'}")
        print(f"    verify     : {verify_str}")
        if status == "FAIL":
            print(f"    best match in text: \"{(window or '')[:200]}\"")
    print(f"  fields: {counts['PASS']} pass / {counts['NULL']} null / {counts['FAIL']} FAIL")

    classification = "BUDGET" if counts["PASS"] > 0 else "INPUT-SIZE"
    reason = (f"{counts['PASS']} passing fields at max_tokens=8000"
              if classification == "BUDGET"
              else "valid JSON but no PASSing fields")
    return {"file": path.name, "classification": classification, "reason": reason,
            "md": md, "md_norm": md_norm, "pass_spans": pass_spans}


async def main():
    targets = resolve_targets()
    print("Resolved target filenames:")
    for p in targets:
        print(f"  - {p.name}")
    print()

    results = []
    for path in targets:
        r = await process(path)
        results.append(r)
        print()

    # --- prove the gate's FAIL path on the first paper ---
    if results:
        first = results[0]
        md_norm = first["md_norm"]
        print("=" * 70)
        print(f"GATE FAIL-PATH PROOF (using {first['file']})")
        status_f, score_f, _ = verify_span(FABRICATED_SPAN, md_norm, first["md"])
        print(f"  fabricated span: {FABRICATED_SPAN!r}")
        print(f"  FABRICATED-SPAN CHECK: score={score_f:.2f} -> "
              f"{'FAIL as expected' if score_f < SPAN_THRESHOLD else 'UNEXPECTED PASS'} (<0.90)")

        if first["pass_spans"]:
            real_span = first["pass_spans"][0]
            real_note = "extracted PASS field source_span"
        else:
            # First paper produced no PASS span; fall back to a guaranteed-real
            # verbatim slice of its own text so the contrast is still shown.
            real_span = first["md"][2000:2150]
            real_note = "verbatim slice of the paper text (no PASS span available)"
        status_r, score_r, _ = verify_span(real_span, md_norm, first["md"])
        print(f"  real span ({real_note}): {real_span[:120]!r}")
        print(f"  REAL-SPAN CHECK: score={score_r:.2f} -> "
              f"{'PASS as expected' if score_r >= SPAN_THRESHOLD else 'UNEXPECTED FAIL'} (>=0.90)")
        print("=" * 70)
        print()

    # --- decision block ---
    print("DECISION")
    print("-" * 70)
    for r in results:
        print(f"  {r['file']}: {r['classification']}  ({r['reason']})")
    classifications = [r["classification"] for r in results]
    if classifications and all(c == "BUDGET" for c in classifications):
        print("\nF3B VERDICT: budget-only")
    else:
        forcing = [r["file"] for r in results if r["classification"] == "INPUT-SIZE"]
        print(f"\nF3B VERDICT: chunking needed  (forced by: {', '.join(forcing) or 'n/a'})")


if __name__ == "__main__":
    asyncio.run(main())
