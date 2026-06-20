"""Heuristic extraction of title and abstract from PDF text."""
import re
from pathlib import Path
from typing import Optional, Tuple

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

from .pdf import first_page_spans, full_text


def extract_title(path: Path, text: str, spans: list) -> Tuple[str, bool, Optional[str]]:
    """
    Extract title with heuristics.
    Returns: (title, needs_review, note)
    """
    needs_review = False
    note = None

    # Candidate A: PDF metadata title
    try:
        doc = pymupdf.open(str(path))
        metadata_title = doc.metadata.get("title", "").strip() if doc.metadata else ""
        doc.close()

        if metadata_title and len(metadata_title) >= 10 and len(metadata_title) <= 300:
            if not any(x in metadata_title.lower() for x in ["microsoft", "document", "untitled"]):
                return metadata_title, False, None
    except Exception:
        pass

    # Candidate B: largest font text on page 0
    if spans:
        page_height = max((s["bbox"][3] for s in spans if s["bbox"]), default=800)
        top_threshold = page_height * 0.4

        top_spans = [s for s in spans if s["bbox"][1] < top_threshold]
        if top_spans:
            max_size = max((s["size"] for s in top_spans), default=0)
            if max_size > 0:
                # Use a relative threshold, not an absolute 1pt tolerance: titles
                # are sometimes set in small caps, where the first letter of each
                # word is a larger drop cap and the rest of the word is smaller.
                # Both belong to the title visually even though they differ >1pt.
                title_spans = [s for s in top_spans if s["size"] >= max_size * 0.75]
                if title_spans:
                    # Reconstruct line breaks from y-position jumps: spans on the
                    # same physical line can still differ in baseline by a couple
                    # of points (drop cap vs. small-caps body), but a real line
                    # break jumps much further. Concatenate within a line (spans
                    # already carry their own internal spacing), join lines with
                    # a single space.
                    lines = []
                    current_line = []
                    last_y0 = None
                    for s in title_spans:
                        y0 = s["bbox"][1]
                        if last_y0 is not None and abs(y0 - last_y0) > 8:
                            lines.append(current_line)
                            current_line = []
                        current_line.append(s)
                        last_y0 = y0
                    if current_line:
                        lines.append(current_line)

                    line_texts = ["".join(s["text"] for s in line).strip() for line in lines]
                    title_text = " ".join(t for t in line_texts if t)
                    title_text = re.sub(r"\s+", " ", title_text).strip()
                    if title_text and 10 <= len(title_text) <= 300:
                        return title_text, False, None

    # Candidate C: first non-empty line
    for line in text.split("\n"):
        line = line.strip()
        if line and len(line) >= 10:
            if len(line) > 300:
                needs_review = True
                note = "Title candidate too long (>300 chars)"
            return line[:300], needs_review, note

    # No title found
    needs_review = True
    note = "No valid title found"
    return "", needs_review, note


def extract_abstract(text: str) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    Extract abstract with heuristics.
    Returns: (abstract, needs_review, note)
    """
    needs_review = False
    note = None

    lines = text.split("\n")

    abstract_start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*abstract\s*(?:[—\.:])?\s*$", line, re.IGNORECASE):
            abstract_start = i + 1
            break

    if abstract_start is None:
        return None, True, "No Abstract section found"

    # Find the end (section header)
    header_pattern = re.compile(
        r"^(?:introduction|1\s+introduction|1\.\s+introduction|i\.\s+introduction|"
        r"keywords|index\s+terms|ccs\s+concepts|categories\s+and\s+subject)",
        re.IGNORECASE
    )

    abstract_end = len(lines)
    for i in range(abstract_start, len(lines)):
        if header_pattern.match(lines[i].strip()):
            abstract_end = i
            break

    abstract_text = "\n".join(lines[abstract_start:abstract_end]).strip()

    if not abstract_text:
        return None, True, "Abstract section is empty"

    if len(abstract_text) < 100:
        needs_review = True
        note = f"Abstract too short ({len(abstract_text)} chars, min 100)"
    elif len(abstract_text) > 3000:
        needs_review = True
        note = f"Abstract too long ({len(abstract_text)} chars, max 3000)"

    return abstract_text if abstract_text else None, needs_review, note
