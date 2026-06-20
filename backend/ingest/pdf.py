"""PDF text extraction using PyMuPDF."""
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


def full_text(path: Path) -> str:
    """Extract all text from a PDF."""
    try:
        doc = pymupdf.open(str(path))
        text_parts = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text:
                text_parts.append(text)
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Warning: Error extracting text from {path}: {e}")
        return ""


def first_page_spans(path: Path) -> list:
    """Extract span data from the first page for title heuristics."""
    try:
        doc = pymupdf.open(str(path))
        if len(doc) == 0:
            doc.close()
            return []

        page = doc[0]
        text_dict = page.get_text("dict")
        spans = []

        if "blocks" in text_dict:
            for block in text_dict["blocks"]:
                if block.get("type") == 0:  # text block
                    if "lines" in block:
                        for line in block["lines"]:
                            if "spans" in line:
                                for span in line["spans"]:
                                    spans.append({
                                        "text": span.get("text", ""),
                                        "size": span.get("size", 0),
                                        "bbox": span.get("bbox", [0, 0, 0, 0])
                                    })

        doc.close()
        return spans
    except Exception as e:
        print(f"Warning: Error extracting spans from {path}: {e}")
        return []
