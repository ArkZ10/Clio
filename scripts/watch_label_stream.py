#!/usr/bin/env python3
"""Diagnostic only -- does NOT touch backend/graph/label.py or write to the DB.

Streams qwen3's raw response live to the terminal so you can watch whether it
ever reaches a label, instead of waiting blind for a non-streaming call to
either finish or time out.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import DB_PATH
from backend.db import connect
from backend.graph.label import _build_messages, _fetch_member_titles
from backend.routing import resolve_stage

import llm_switch


async def main():
    cluster_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    db = connect(DB_PATH)
    cursor = db.cursor()

    if cluster_id is None:
        cursor.execute("SELECT id FROM cluster WHERE exploration_id IS NULL AND id != -1 ORDER BY id LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            print("No real clusters found.")
            return
        cluster_id = row[0]

    titles = _fetch_member_titles(cursor, cluster_id)
    db.close()

    print(f"=== Cluster {cluster_id} ===")
    for t in titles:
        print(f"  - {t}")
    print()
    print("--- streaming raw output (Ctrl+C to stop watching) ---")
    print()

    messages = _build_messages(titles)
    endpoint = resolve_stage("cluster_label")

    async for ev in llm_switch.stream(messages, endpoint.name, thinking=False, max_tokens=3000):
        if "delta" in ev:
            print(ev["delta"], end="", flush=True)

    print()
    print()
    print("--- end of stream ---")


if __name__ == "__main__":
    asyncio.run(main())
