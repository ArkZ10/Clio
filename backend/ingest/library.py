"""Library ingestion - scan PDFs and insert paper rows."""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

from backend.config import PDF_DIR, DB_PATH
from backend.db import connect, init_db
from .pdf import full_text, first_page_spans
from .metadata import extract_title, extract_abstract


class IngestResult:
    def __init__(self):
        self.ingested = 0
        self.flagged = 0
        self.skipped = 0
        self.papers = []  # (filename, title, status, note)


def paper_exists(db: sqlite3.Connection, pdf_path: str) -> bool:
    """Check if a paper with this pdf_path already exists."""
    cursor = db.cursor()
    cursor.execute("SELECT 1 FROM paper WHERE pdf_path = ?", (pdf_path,))
    return cursor.fetchone() is not None


def ingest_library() -> IngestResult:
    """Scan PDF folder and ingest papers."""
    result = IngestResult()

    # Initialize database schema
    init_db(DB_PATH)

    if not PDF_DIR.exists():
        return result

    db = connect(DB_PATH)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))

    for pdf_path_obj in pdf_files:
        pdf_path_str = str(pdf_path_obj.resolve())

        # Check idempotency
        if paper_exists(db, pdf_path_str):
            result.skipped += 1
            result.papers.append((pdf_path_obj.name, "", "SKIP", "Already ingested"))
            continue

        # Extract text
        text = full_text(pdf_path_obj)
        if not text or len(text) < 200:
            # Flag scanned/garbage PDFs
            cursor = db.cursor()
            cursor.execute(
                """INSERT INTO paper
                   (title, source, pdf_path, full_text, needs_review, ingest_notes, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    pdf_path_obj.stem,
                    "library",
                    pdf_path_str,
                    text,
                    1,
                    "Low text content (likely scanned or corrupted PDF)",
                    datetime.now(),
                ),
            )
            db.commit()
            result.flagged += 1
            result.papers.append((
                pdf_path_obj.name,
                pdf_path_obj.stem,
                "REVIEW",
                "Low text content"
            ))
            continue

        # Extract title
        spans = first_page_spans(pdf_path_obj)
        title, title_review, title_note = extract_title(pdf_path_obj, text, spans)

        # Extract abstract
        abstract, abstract_review, abstract_note = extract_abstract(text)

        needs_review = title_review or abstract_review
        ingest_notes_parts = []
        if title_note:
            ingest_notes_parts.append(f"Title: {title_note}")
        if abstract_note:
            ingest_notes_parts.append(f"Abstract: {abstract_note}")
        ingest_notes = " | ".join(ingest_notes_parts) if ingest_notes_parts else None

        # Insert paper
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO paper
               (title, abstract, source, pdf_path, full_text, needs_review, ingest_notes, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                abstract,
                "library",
                pdf_path_str,
                text,
                1 if needs_review else 0,
                ingest_notes,
                datetime.now(),
            ),
        )
        db.commit()

        if needs_review:
            result.flagged += 1
            status = "REVIEW"
            note = ingest_notes_parts[0] if ingest_notes_parts else "Needs review"
        else:
            result.ingested += 1
            status = "OK"
            note = ""

        result.papers.append((pdf_path_obj.name, title[:60], status, note))

    db.close()
    return result
