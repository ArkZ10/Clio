# Clio

A single-user research-mapping tool. An [Obsidian](https://obsidian.md) vault is the
source of truth: Clio turns it into a navigable graph and answers questions grounded
strictly in what the vault actually says  if a topic isn't covered, it says so rather
than fabricating an answer. Alongside that, Clio can search arXiv and read your library
of papers.

## Features (live in the app today)

- **Vault graph** (`/vault`) — the wiki's notes and `[[wikilinks]]` rendered as a
  navigable graph, read directly from the Obsidian vault. Strictly read-only — Clio
  never writes back to it.
- **Grounded chat** (`/`, `/library`, `/vault`) — ask questions and get answers built
  only from vault pages the model actually selected as relevant, streamed token by
  token. Two guards against fabrication: an empty selection short-circuits before any
  answer is generated, and the answer prompt is instructed to say plainly when the
  selected pages don't cover the question rather than infer past it. Chat threads
  persist per surface and resume automatically.
- **Library** (`/library`) — the vault's curated papers (`wiki/sources/`) in a
  split list/viewer, with PDF and note views and wikilink navigation between them.
- **Explore** (`/explore`) — live arXiv search with paged results, year filtering, and
  a split list/viewer that opens either the abstract (title, authors, categories,
  full summary, comment/journal-ref/DOI) or the PDF.
- **Settings** (`/settings`) — register LLM endpoints (local or cloud, API key stored
  encrypted or referenced via an env var) and choose which one answers chat.

## Repo layout

| Path | What it is |
| --- | --- |
| `backend/` | FastAPI app: vault reading + grounded chat (`chat.py`, `vault.py`), library/explore/settings routes, LLM routing (`routing.py`), chat session persistence (`chat_store.py`), the offline pipeline (`graph/` — kNN + HDBSCAN clustering, `explore/` — arXiv retrieve/rerank) |
| `packages/llm_switch/` | Local editable package: swappable local/cloud LLM endpoint registry and call layer |
| `scripts/` | Offline pipeline jobs and one-off migrations (embed, cluster, extract, synthesize, build graph edges, diagnostics) — not called by the running app; see below |
| `data/` | SQLite DB (`clio.db`), fetched PDFs, and caches. Gitignored — not in version control |
| `web/` | Frontend UI (TanStack Start + Vite + React) |
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

Requires `CLIO_VAULT_PATH` set in the root `.env` (see `.env.example`), pointing at
the Obsidian vault — the graph and chat routes read directly from it.

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

### Offline pipeline jobs

Separate from anything the running app calls: retrieving and embedding papers,
clustering them, extracting grounded fields, and synthesizing per-cluster summaries
are batch jobs run by hand against the local DB, not live endpoints. For example:

```bash
./venv/bin/python scripts/build_graph.py
```

Which model runs each of these offline stages (rerank / extract / synthesis) is
still configurable via per-stage LLM routing in `backend/routing.py`, independent of
which model Settings has chosen for live chat.
