#!/usr/bin/env bash
# Runs backend + frontend together for local dev. Ctrl-C (or any kill of this
# script) kills the whole process group via the trap below -- neither side is
# meant to outlive the other.
set -e
cd "$(dirname "$0")"
trap 'kill 0' INT TERM EXIT

./run_backend.sh 2>&1 | sed -u 's/^/[backend] /' &
( cd web && npm run dev ) 2>&1 | sed -u 's/^/[web]     /' &

wait
