#!/usr/bin/env python3
"""Generate LLM cluster labels and print an inspectable report."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

# cluster_label routes to deepseek -- load .env so DEEPSEEK_API_KEY resolves
# regardless of the calling shell's environment.
dotenv.load_dotenv(ROOT / ".env")

from backend.graph.label import label_clusters


async def main():
    report = await label_clusters()

    for entry in report:
        print(f"=== Cluster {entry['cluster_id']} ({entry['member_count']} members) ===")
        for title in entry["titles"]:
            print(f"  - {title}")
        print(f"  raw model text: {entry['raw_text']!r}")
        print(f"  llm_label:      {entry['llm_label']!r}")
        print()

    print(f"{len(report)} cluster(s) processed.")


if __name__ == "__main__":
    asyncio.run(main())
