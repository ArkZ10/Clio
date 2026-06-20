#!/usr/bin/env python3
"""CLI for library PDF ingestion."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ingest.library import ingest_library


def main():
    print("Starting library ingestion...")
    result = ingest_library()

    print("\n" + "=" * 80)
    for filename, title, status, note in result.papers:
        title_str = title[:60] if title else "(no title)"
        if status == "OK":
            print(f"{filename:40} → {title_str:30} OK")
        elif status == "REVIEW":
            print(f"{filename:40} → {title_str:30} REVIEW: {note}")
        elif status == "SKIP":
            print(f"{filename:40} → (skipped)")

    print("=" * 80)
    print(
        f"Summary: {result.ingested} ingested, {result.flagged} flagged for review, "
        f"{result.skipped} skipped (already present)"
    )


if __name__ == "__main__":
    main()
