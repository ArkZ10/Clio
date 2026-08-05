"""Storage for persistent vault-chat conversations: chat_session / chat_message
in clio.db (see db.py). Plain sqlite3, same connect()/close() pattern as
routes/library.py -- no ORM.

Sessions are bucketed by (surface, page_context); see db.py. This module just
stores that pair, routes/chat.py decides what it means.
"""
from __future__ import annotations

import json

from backend.config import DB_PATH
from backend.db import connect

TITLE_MAX_LEN = 60


def _title_from(text: str) -> str:
    """Title from the first user message -- a truncated snippet, not an LLM
    call."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= TITLE_MAX_LEN:
        return collapsed
    return collapsed[:TITLE_MAX_LEN].rstrip() + "…"


def list_sessions(surface: str) -> list[dict]:
    """All sessions for one surface, newest first."""
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "SELECT id, page_context, title, created_at, updated_at "
        "FROM chat_session WHERE surface = ? ORDER BY updated_at DESC",
        (surface,),
    )
    rows = cur.fetchall()
    db.close()
    return [
        {
            "id": r[0],
            "page_context": r[1],
            "title": r[2] or "New chat",
            "created_at": r[3],
            "updated_at": r[4],
        }
        for r in rows
    ]


def get_session(session_id: int) -> dict | None:
    """Session metadata plus its messages, oldest first. None if not found."""
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "SELECT id, surface, page_context, title, created_at, updated_at "
        "FROM chat_session WHERE id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    if row is None:
        db.close()
        return None

    cur.execute(
        "SELECT role, content, cited_pages, selected_pages, dropped_count, "
        "no_coverage, created_at FROM chat_message WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    )
    messages = [
        {
            "role": m[0],
            "content": m[1],
            "cited_pages": json.loads(m[2]) if m[2] else [],
            "selected_pages": json.loads(m[3]) if m[3] else [],
            "dropped_count": m[4],
            "no_coverage": bool(m[5]) if m[5] is not None else None,
            "created_at": m[6],
        }
        for m in cur.fetchall()
    ]
    db.close()
    return {
        "id": row[0],
        "surface": row[1],
        "page_context": row[2],
        "title": row[3] or "New chat",
        "created_at": row[4],
        "updated_at": row[5],
        "messages": messages,
    }


def create_session(surface: str, page_context: str | None) -> int:
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "INSERT INTO chat_session (surface, page_context, title) VALUES (?, ?, NULL)",
        (surface, page_context),
    )
    db.commit()
    session_id = cur.lastrowid
    db.close()
    return session_id


def append_message(
    session_id: int,
    role: str,
    content: str,
    *,
    cited_pages: list[str] | None = None,
    selected_pages: list[str] | None = None,
    dropped_count: int | None = None,
    no_coverage: bool | None = None,
) -> None:
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "INSERT INTO chat_message "
        "(session_id, role, content, cited_pages, selected_pages, dropped_count, no_coverage) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            role,
            content,
            json.dumps(cited_pages) if cited_pages is not None else None,
            json.dumps(selected_pages) if selected_pages is not None else None,
            dropped_count,
            None if no_coverage is None else int(no_coverage),
        ),
    )
    # Title on the first user message.
    if role == "user":
        cur.execute("SELECT title FROM chat_session WHERE id = ?", (session_id,))
        existing = cur.fetchone()
        if existing is not None and not existing[0]:
            cur.execute(
                "UPDATE chat_session SET title = ? WHERE id = ?",
                (_title_from(content), session_id),
            )
    cur.execute(
        "UPDATE chat_session SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )
    db.commit()
    db.close()


def delete_session(session_id: int) -> bool:
    """True if deleted, False if the id didn't exist. No FK cascade in sqlite3
    here, so messages are deleted explicitly."""
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute("SELECT 1 FROM chat_session WHERE id = ?", (session_id,))
    if cur.fetchone() is None:
        db.close()
        return False
    cur.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM chat_session WHERE id = ?", (session_id,))
    db.commit()
    db.close()
    return True


def recent_messages(session_id: int, limit_turns: int) -> list[dict]:
    """Last `limit_turns` messages as [{role, content}], oldest first. Feeds
    the answer step's history param."""
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "SELECT role, content FROM chat_message WHERE session_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (session_id, limit_turns),
    )
    rows = list(reversed(cur.fetchall()))
    db.close()
    return [{"role": r[0], "content": r[1]} for r in rows]
