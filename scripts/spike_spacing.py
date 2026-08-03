#!/usr/bin/env python3
"""THROWAWAY DIAGNOSTIC SPIKE #2 -- measure pymupdf4llm space-collapse rate.

Measures how often pymupdf4llm fuses words together (e.g. "OT-FMtrulystarts")
across the whole library. Writes NOTHING to the DB, builds no pipeline, fixes
nothing -- pure measurement. Delete when done.
"""
import re
import statistics
from pathlib import Path

import pymupdf4llm

ROOT = Path(__file__).parent.parent
PDF_DIR = ROOT / "data" / "papers" / "pdfs"

# 26+ consecutive letters with no space/punctuation = almost certainly multiple
# fused words; genuine English/technical words rarely exceed 25.
GLUED_RE = re.compile(r"[A-Za-z]{26,}")


def analyze(md: str) -> dict:
    words = md.split()
    word_count = len(words)
    glued = GLUED_RE.findall(md)

    paragraphs = re.split(r"\n\s*\n", md)
    para_total = len([p for p in paragraphs if p.strip()])
    para_with_glued = sum(1 for p in paragraphs if p.strip() and GLUED_RE.search(p))

    per_10k = round(len(glued) / word_count * 10000, 2) if word_count else 0.0

    return {
        "words": word_count,
        "glued_count": len(glued),
        "glued_per_10k": per_10k,
        "examples": glued[:5],
        "para_with_glued": para_with_glued,
        "para_total": para_total,
    }


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in data/papers/pdfs/. Nothing to measure.")
        return

    print(f"Processing all {len(pdfs)} PDF(s)...\n")

    results = []
    for path in pdfs:
        md = pymupdf4llm.to_markdown(str(path))
        stats = analyze(md)
        stats["filename"] = path.name
        results.append(stats)

    # Per-paper table
    print("=" * 110)
    print(f"{'filename':<46} | {'words':>6} | {'glued':>5} | {'per_10k':>7} | {'glued_paras/total':>18}")
    print("-" * 110)
    for r in results:
        name = r["filename"][:44]
        paras = f"{r['para_with_glued']}/{r['para_total']}"
        print(f"{name:<46} | {r['words']:>6} | {r['glued_count']:>5} | {r['glued_per_10k']:>7} | {paras:>18}")
    print("=" * 110)

    # Show examples per paper (so the table above stays scannable)
    print("\nExample glued tokens (up to 5 per paper, truncated to 40 chars):")
    for r in results:
        if r["examples"]:
            ex = ", ".join(e[:40] for e in r["examples"])
            print(f"  {r['filename'][:44]}: {ex}")

    # Summary
    clean = [r for r in results if r["glued_count"] == 0]
    minor = [r for r in results if 1 <= r["glued_count"] <= 5]
    significant = [r for r in results if r["glued_count"] > 5]
    per_10k_values = [r["glued_per_10k"] for r in results]
    worst = max(results, key=lambda r: r["glued_per_10k"])

    print("\n" + "=" * 110)
    print("SUMMARY")
    print("-" * 110)
    print(f"  total PDFs processed:        {len(results)}")
    print(f"  clean (glued_count == 0):    {len(clean)}")
    print(f"  minor (glued_count 1-5):     {len(minor)}")
    print(f"  significant (glued_count >5):{len(significant)}")
    print(f"  median glued_per_10k:        {round(statistics.median(per_10k_values), 2)}")
    print(f"  max glued_per_10k:           {round(max(per_10k_values), 2)}")
    print(f"\n  WORST paper by glued_per_10k: {worst['filename']}")
    print(f"    glued_per_10k={worst['glued_per_10k']}  glued_count={worst['glued_count']}  words={worst['words']}")
    print(f"    examples:")
    for e in worst["examples"]:
        print(f"      - {e[:40]}")
    print("=" * 110)


if __name__ == "__main__":
    main()
