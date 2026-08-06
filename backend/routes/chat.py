"""Vault chat route: index-first retrieval, grounded answering.

Read-only -- like every other /vault/* endpoint, this never writes to the vault.
"""
import json

import llm_switch
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import backend.chat_store as chat_store
from backend.chat import (
    MAX_HISTORY_TURNS,
    SelectionFailed,
    answer,
    answer_stream,
    load_records,
    select_pages,
)
from backend.routes.vault import _resolve_vault

router = APIRouter()

# Each surface keeps its own thread (see db.py). Validated here so a typo'd
# surface doesn't silently create a bucket nothing ever lists.
SURFACES = ("home", "library", "vault")


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    # A page stem. When set, that page is always included in the fetched set.
    page_context: str | None = None
    # Used only for answering, never page selection. Ignored if session_id is
    # set -- the stored history wins.
    history: list[ChatTurn] | None = None
    # When set, this exchange is persisted onto that session and its history
    # feeds the answer step. Omit for a one-off, unpersisted call.
    session_id: int | None = None


class CreateSessionRequest(BaseModel):
    surface: str
    page_context: str | None = None


def _check_question(req: ChatRequest) -> str:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")
    return question


def _check_session(session_id: int | None) -> None:
    if session_id is not None and chat_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"No chat session {session_id}")


async def _select_stems(question: str, req: ChatRequest, records: dict) -> tuple[list[str], int]:
    """Runs page selection and merges in page_context, mapping failures to
    HTTP errors -- shared by /vault/chat and /vault/chat/stream."""
    try:
        selected, dropped = await select_pages(question, records)
    except SelectionFailed as e:
        # A broken selection step is an error, not "not in your wiki".
        raise HTTPException(status_code=502, detail=str(e)) from e
    except llm_switch.LLMError as e:
        status = 429 if getattr(e, "status_code", None) == 429 else 502
        raise HTTPException(
            status_code=status, detail=f"LLM call failed: {e.message}"
        ) from e

    # page_context is merged in unconditionally, so a node-click question is
    # answered from that page even if selection missed it.
    stems = list(selected)
    if req.page_context and req.page_context in records:
        if req.page_context not in stems:
            stems.insert(0, req.page_context)
    return stems, dropped


def _resolve_history(req: ChatRequest) -> list[dict] | None:
    """A session's stored history wins over any client-supplied one."""
    if req.session_id is not None:
        return chat_store.recent_messages(req.session_id, MAX_HISTORY_TURNS)
    return [t.model_dump() for t in req.history] if req.history else None


@router.post("/vault/chat")
async def post_vault_chat(req: ChatRequest):
    vault = _resolve_vault()
    question = _check_question(req)
    _check_session(req.session_id)

    # ONE vault scan for the whole request; find_page() would rescan per page.
    records = load_records(vault)
    stems, dropped = await _select_stems(question, req, records)
    history = _resolve_history(req)

    try:
        text, cited, did_answer = await answer(question, stems, records, history)
    except llm_switch.LLMError as e:
        status = 429 if getattr(e, "status_code", None) == 429 else 502
        raise HTTPException(
            status_code=status, detail=f"LLM call failed: {e.message}"
        ) from e

    no_coverage = (not stems) or (not did_answer)

    if req.session_id is not None:
        chat_store.append_message(req.session_id, "user", question)
        chat_store.append_message(
            req.session_id,
            "assistant",
            text,
            cited_pages=cited,
            selected_pages=stems,
            dropped_count=dropped,
            no_coverage=no_coverage,
        )

    return {
        "answer": text,
        "cited_pages": cited,
        "selected_pages": stems,
        "dropped_count": dropped,
        # True on either guard -- see backend/chat.py's answer().
        "no_coverage": no_coverage,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/vault/chat/stream")
async def post_vault_chat_stream(req: ChatRequest):
    """Same retrieval + answering as /vault/chat, streamed as SSE. Events:
      {"type": "selected", "selected_pages": [...], "dropped_count": n} --
        first, as soon as page selection resolves (before the slower answer
        call even starts), so the client has something to show besides a
        blank spinner during the model's hidden reasoning phase.
      {"type": "start", no_coverage, cited_pages, selected_pages, dropped_count}
      {"type": "delta", "text": "..."}
      {"type": "done"}
      {"type": "error", "detail": "..."}  -- only for a failure mid-stream,
        after the 200 response has already started -- an HTTP status can't
        change at that point, so the error has to travel in-band instead.
    Everything that can fail before the stream opens (bad question, unknown
    session, a broken selection call) still raises a normal HTTPException.
    """
    vault = _resolve_vault()
    question = _check_question(req)
    _check_session(req.session_id)

    records = load_records(vault)
    stems, dropped = await _select_stems(question, req, records)
    history = _resolve_history(req)

    async def event_stream():
        yield _sse({"type": "selected", "selected_pages": stems, "dropped_count": dropped})
        full_text: list[str] = []
        no_coverage = not stems
        cited: list[str] = []
        try:
            async for event in answer_stream(question, stems, records, history):
                if event["type"] == "coverage":
                    no_coverage = event["no_coverage"]
                    cited = event["cited_pages"]
                    yield _sse(
                        {
                            "type": "start",
                            "no_coverage": no_coverage,
                            "cited_pages": cited,
                            "selected_pages": stems,
                            "dropped_count": dropped,
                        }
                    )
                elif event["type"] == "delta":
                    full_text.append(event["text"])
                    yield _sse({"type": "delta", "text": event["text"]})
                elif event["type"] == "done":
                    yield _sse({"type": "done"})
        except llm_switch.LLMError as e:
            yield _sse({"type": "error", "detail": f"LLM call failed: {e.message}"})
            return

        if req.session_id is not None:
            chat_store.append_message(req.session_id, "user", question)
            chat_store.append_message(
                req.session_id,
                "assistant",
                "".join(full_text),
                cited_pages=cited,
                selected_pages=stems,
                dropped_count=dropped,
                no_coverage=no_coverage,
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/vault/chat/sessions")
async def list_chat_sessions(surface: str):
    if surface not in SURFACES:
        raise HTTPException(
            status_code=400, detail=f"surface must be one of {SURFACES}, got '{surface}'"
        )
    return {"sessions": chat_store.list_sessions(surface)}


@router.post("/vault/chat/sessions")
async def create_chat_session(req: CreateSessionRequest):
    if req.surface not in SURFACES:
        raise HTTPException(
            status_code=400, detail=f"surface must be one of {SURFACES}, got '{req.surface}'"
        )
    return {"id": chat_store.create_session(req.surface, req.page_context)}


@router.get("/vault/chat/sessions/{session_id}")
async def get_chat_session(session_id: int):
    session = chat_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No chat session {session_id}")
    return session


@router.delete("/vault/chat/sessions/{session_id}")
async def delete_chat_session(session_id: int):
    if not chat_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"No chat session {session_id}")
    return {"ok": True}
