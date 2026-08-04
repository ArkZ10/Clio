"""Vault chat route: index-first retrieval, grounded answering.

Read-only -- like every other /vault/* endpoint, this never writes to the vault.
"""
import llm_switch
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.chat import SelectionFailed, answer, load_records, select_pages
from backend.routes.vault import _resolve_vault

router = APIRouter()


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    # A page stem. When set (the node-click flow), that page is ALWAYS included
    # in the fetched set, on top of whatever index selection returns.
    page_context: str | None = None
    # Recent turns, used ONLY for answering -- never for page selection, so
    # history can't bias retrieval or smuggle in coverage.
    history: list[ChatTurn] | None = None


@router.post("/vault/chat")
async def post_vault_chat(req: ChatRequest):
    vault = _resolve_vault()

    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    # ONE vault scan for the whole request; find_page() would rescan per page.
    records = load_records(vault)

    try:
        selected, dropped = await select_pages(question, records)

        # page_context is merged in unconditionally, so a question asked from a
        # node click is answered from that page even if index selection missed
        # it. It also means a page_context request is never "no coverage".
        stems = list(selected)
        if req.page_context and req.page_context in records:
            if req.page_context not in stems:
                stems.insert(0, req.page_context)

        history = [t.model_dump() for t in req.history] if req.history else None
        text, cited = await answer(question, stems, records, history)
    except SelectionFailed as e:
        # A broken selection step must NOT be reported as "your wiki doesn't
        # cover this" -- that would be a confident false negative.
        raise HTTPException(status_code=502, detail=str(e)) from e
    except llm_switch.LLMError as e:
        # First LLMError -> HTTP mapping in the codebase. 429 is passed through
        # so a client can back off; everything else is an upstream failure.
        status = 429 if getattr(e, "status_code", None) == 429 else 502
        raise HTTPException(
            status_code=status, detail=f"LLM call failed: {e.message}"
        ) from e

    return {
        "answer": text,
        "cited_pages": cited,
        "selected_pages": stems,
        "dropped_count": dropped,
        # NOTE: this reflects the empty-selection case only. If selection
        # over-picked loosely-related pages and the answer then hedges, this is
        # still False -- a known V2 limitation, see backend/chat.py.
        "no_coverage": not stems,
    }
