#!/usr/bin/env bash
# Runs the Clio backend via uv, reusing the existing ./venv (no re-resolve/re-sync
# of the heavy ML stack). Host/port are set in backend/config.py (override with
# CLIO_HOST / CLIO_PORT env vars).
cd "$(dirname "$0")"
UV_PROJECT_ENVIRONMENT=./venv uv run --no-sync -- python -m backend.app
