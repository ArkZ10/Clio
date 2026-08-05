#!/usr/bin/env python3
"""Live smoke test for llm_switch's call() and stream(), against real
endpoints. Loads Clio/.env itself (llm_switch never touches dotenv) so
DEEPSEEK_API_KEY is available regardless of the calling shell's environment.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

dotenv.load_dotenv(ROOT / ".env")

from llm_switch import call, stream, register_endpoint

ENDPOINTS = ["local-ollama", "deepseek"]


def ensure_endpoints_registered():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("FAILED: DEEPSEEK_API_KEY is not set even after loading .env.")
        print(f"  Checked: {ROOT / '.env'}")
        print("  Add DEEPSEEK_API_KEY=... to that file and re-run.")
        sys.exit(1)

    register_endpoint(
        "local-ollama", "http://localhost:11434", kind="auto",
        default_model=os.environ.get("OLLAMA_MODEL", "qwen3:4b"),
    )
    register_endpoint(
        "deepseek",
        "https://api.deepseek.com",
        api_key="env:DEEPSEEK_API_KEY",
        kind="auto",
        default_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )


async def check_endpoint(name: str):
    print("===", name, "===")

    r = await call(
        [{"role": "user", "content": "Reply with exactly: pong"}], name, max_tokens=300
    )
    print("non-stream text:", repr(r.text))
    assert r.text.strip(), "empty non-stream response"
    assert "<think>" not in r.text, "reasoning leaked into text"
    print("usage:", r.usage)

    chunks = []
    got = False
    async for ev in stream(
        [{"role": "user", "content": "Count: 1 2 3"}], name, max_tokens=300
    ):
        if "delta" in ev and not ev.get("thinking"):
            chunks.append(ev["delta"])
            got = True
    streamed = "".join(chunks)
    print("streamed text:", repr(streamed))
    assert got, "no deltas received from stream"
    assert "<think>" not in streamed, "reasoning leaked into streamed text"
    assert "</think>" not in streamed, "reasoning leaked into streamed text"
    assert streamed.strip(), "streamed visible text is empty"


async def main():
    ensure_endpoints_registered()
    for name in ENDPOINTS:
        await check_endpoint(name)
    print()
    print("SMOKE PASSED (both endpoints)")


if __name__ == "__main__":
    asyncio.run(main())
