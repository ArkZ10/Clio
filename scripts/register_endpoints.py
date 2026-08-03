#!/usr/bin/env python3
"""Canonical endpoint registration -- the single place that writes the
llm_switch registry. Model names come from .env so switching models is an
.env edit, not a code change.

Run after editing any *_MODEL var in .env:
    ./venv/bin/python scripts/register_endpoints.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

dotenv.load_dotenv(ROOT / ".env")

import llm_switch

# (env var, fallback default) -- fallback used only if the var is absent from .env
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-pro")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")


def register_all():
    llm_switch.register_endpoint(
        "local-ollama", "http://localhost:11434",
        kind="auto", default_model=OLLAMA_MODEL,
    )
    llm_switch.register_endpoint(
        "deepseek", "https://api.deepseek.com",
        api_key="env:DEEPSEEK_API_KEY", kind="auto", default_model=DEEPSEEK_MODEL,
    )
    llm_switch.register_endpoint(
        "nvidia", "https://integrate.api.nvidia.com/v1",
        api_key="env:NVIDIA_API_KEY", kind="auto", default_model=NVIDIA_MODEL,
    )


def main():
    register_all()
    print("Registered endpoints (model names from .env):")
    for e in llm_switch.list_endpoints():
        print(f"  {e.name:14} -> {e.default_model}")


if __name__ == "__main__":
    main()
