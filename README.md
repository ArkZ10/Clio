# Clio

A single-user research-mapping tool: ingest papers, embed and cluster them into a
navigable graph, and synthesize grounded summaries of the resulting research camps.

## Repo layout

| Path | What it is |
| --- | --- |
| `backend/` | FastAPI app + the pipeline: ingest, embedders, graph (kNN + HDBSCAN + labeling), explore (arXiv retrieve/rerank), routes, per-stage LLM routing |
| `packages/llm_switch/` | Local editable package: swappable local/cloud LLM endpoint registry and call layer |
| `scripts/` | Offline pipeline jobs and one-off migrations (embed, cluster, extract, synthesize, build graph edges, diagnostics) |
| `data/` | SQLite DB (`clio.db`), fetched PDFs, and caches. Gitignored — not in version control |
| `web/` | Frontend UI (TanStack Start + Vite + React)|
| `venv/` | Python virtualenv. Gitignored |

## Running

### Backend (FastAPI, port 8000)

```bash
./run_backend.sh
```

Host and port are defined in code (`backend/config.py`), overridable via the
`CLIO_HOST` / `CLIO_PORT` environment variables. The script runs the app through
`uv` against the existing `./venv`, equivalent to:

```bash
UV_PROJECT_ENVIRONMENT=./venv uv run --no-sync -- python -m backend.app
```

Or without `uv`, directly:

```bash
./venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Health check: `curl http://localhost:8000/health` → `{"status":"ok"}`

### Web (TanStack Start + Vite)

```bash
cd web
npm install
npm run dev       # vite dev server
npm run build     # production build
npm run preview   # serve the production build
npm run lint      # eslint
npm run format    # prettier --write
```

Copy `web/.env.example` to `web/.env` and set `VITE_API_URL` (e.g.
`http://localhost:8000`) to point the UI at the FastAPI backend above. Real
`.env` files are gitignored.

`web/` is wired to the backend: the vault graph (`/vault`) reads
`/vault/graph` + `/vault/page/{stem}`, and chat everywhere (`/`, `/library`,
`/vault`) is grounded in the vault via `/vault/chat`. Both require
`CLIO_VAULT_PATH` set in the root `.env` (see `.env.example`) and the backend
running.

### Offline pipeline jobs

Pipeline steps run as scripts against the same venv, for example:

```bash
./venv/bin/python scripts/build_graph.py
./venv/bin/python scripts/label_clusters.py
```
