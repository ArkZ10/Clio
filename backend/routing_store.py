"""Persisted per-stage routing overrides: stage_route in clio.db. Lets a
stage's endpoint be changed at runtime; routing.route_name() falls back to
DEFAULT_ROUTES when no override exists.
"""
import sqlite3

from backend.config import DB_PATH
from backend.db import connect


def get_override(stage: str) -> str | None:
    """None if there's no override -- including when stage_route doesn't
    exist yet (init_db() never ran in this process, e.g. a script calling
    resolve_stage directly). A missing table means "no overrides", not a
    crash -- route_name() must keep working with only DEFAULT_ROUTES."""
    db = connect(DB_PATH)
    cur = db.cursor()
    try:
        cur.execute("SELECT endpoint_name FROM stage_route WHERE stage = ?", (stage,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    db.close()
    return row[0] if row else None


def list_overrides() -> dict[str, str]:
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute("SELECT stage, endpoint_name FROM stage_route")
    rows = cur.fetchall()
    db.close()
    return dict(rows)


def set_override(stage: str, endpoint_name: str) -> None:
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "INSERT INTO stage_route (stage, endpoint_name) VALUES (?, ?) "
        "ON CONFLICT(stage) DO UPDATE SET "
        "endpoint_name = excluded.endpoint_name, updated_at = CURRENT_TIMESTAMP",
        (stage, endpoint_name),
    )
    db.commit()
    db.close()


def clear_override(stage: str) -> None:
    db = connect(DB_PATH)
    cur = db.cursor()
    cur.execute("DELETE FROM stage_route WHERE stage = ?", (stage,))
    db.commit()
    db.close()
