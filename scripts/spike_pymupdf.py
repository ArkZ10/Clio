#!/usr/bin/env python3
"""THROWAWAY DIAGNOSTIC SPIKE -- evaluate pymupdf4llm extraction quality.

Writes NOTHING to the database, imports NOTHING from backend/, builds no
pipeline. Reads a few real library PDFs, dumps their markdown to spike_out/,
and prints a quality readout. Delete this script and spike_out/ when done.
"""
import re
from pathlib import Path

import pymupdf4llm

ROOT = Path(__file__).parent.parent
PDF_DIR = ROOT / "data" / "papers" / "pdfs"
OUT_DIR = ROOT / "spike_out"

SECTION_WORDS = {
    "Abstract": ["abstract"],
    "Introduction": ["introduction"],
    "Method": ["method", "methods", "approach"],
    "Results": ["results", "experiments"],
    "References": ["references"],
}


def heading_or_bold_lines(md: str) -> list[str]:
    """Lines that are markdown headings (#...) or fully-bold (**...**) --
    where section titles tend to land."""
    out = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            out.append(s.lstrip("#").strip().lower())
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            out.append(s.strip("*").strip().lower())
    return out


def section_present(md: str, variants: list[str]) -> bool:
    candidates = heading_or_bold_lines(md)
    for line in candidates:
        for v in variants:
            # match the section word as a leading token of the heading/bold line
            if line == v or line.startswith(v):
                return True
    return False


def mid_sentence_newlines(md: str) -> int:
    """Count of '\\n' NOT followed by another '\\n', '#', '-', or '*' --
    a rough proxy for in-paragraph line breaks vs real paragraph/structure
    breaks."""
    count = 0
    for i, ch in enumerate(md):
        if ch != "\n":
            continue
        nxt = md[i + 1] if i + 1 < len(md) else ""
        if nxt not in ("\n", "#", "-", "*"):
            count += 1
    return count


def main():
    OUT_DIR.mkdir(exist_ok=True)

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    chosen = pdfs[: min(3, len(pdfs))]

    print(f"Found {len(pdfs)} PDF(s); processing first {len(chosen)}:")
    for p in chosen:
        print(f"  - {p.name}")
    print()

    for path in chosen:
        md = pymupdf4llm.to_markdown(str(path))

        out_path = OUT_DIR / f"{path.stem}.md"
        out_path.write_text(md, encoding="utf-8")

        header_count = sum(1 for line in md.splitlines() if line.lstrip().startswith("#"))
        hyphen_artifacts = md.count("-\n")
        mid_nl = mid_sentence_newlines(md)

        print("=" * 90)
        print(f"FILE: {path.name}")
        print(f"  markdown chars:        {len(md)}")
        print(f"  markdown headers (#):  {header_count}")
        print(f"  section headings present:")
        for label, variants in SECTION_WORDS.items():
            present = section_present(md, variants)
            print(f"      {label:14} {'PRESENT' if present else 'absent'}")
        print(f"  hard-hyphenation artifacts ('-\\n'): {hyphen_artifacts}")
        print(f"  mid-sentence newline indicator:     {mid_nl}")
        print(f"  --- first 1000 chars ---")
        print(md[:1000])
        print(f"  --- end first 1000 chars ---")
        print()


if __name__ == "__main__":
    main()
