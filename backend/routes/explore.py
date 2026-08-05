"""Read-only explore routes. Mirrors routes/library.py's query shape, scoped
to explore data -- no shared logic or router between the two.
"""
import json

from fastapi import APIRouter

from backend.config import DB_PATH
from backend.db import connect

EXPLORE_EXPLORATION_ID = 1
EXPLORE_LAYER = "semantic_explore_1"  # distinct from library's 'semantic'

router = APIRouter()


@router.get("/explore/graph")
async def get_explore_graph():
    db = connect(DB_PATH)
    cursor = db.cursor()

    # nodes: p.source='explore' is the direct, unambiguous identifier for
    # explore papers (mirrors library's p.source='library' filter exactly).
    # LEFT JOIN so an explore paper with no cluster assignment (HDBSCAN noise,
    # or the folded small cluster) still appears as a node, cluster=-1 --
    # same COALESCE-to--1 pattern as library's get_graph().
    cursor.execute(
        """
        SELECT p.id, p.title, pc.cluster_id
        FROM paper p
        LEFT JOIN paper_cluster pc ON pc.paper_id = p.id
        WHERE p.source = 'explore'
        """
    )
    nodes = [
        {"id": row[0], "title": row[1], "cluster": row[2] if row[2] is not None else -1}
        for row in cursor.fetchall()
    ]

    # links: layer='semantic_explore_1' is the W1 isolation tag -- exact string
    # match, so this can NEVER return library's layer='semantic' edges (and
    # library's own query, unchanged, can never return these).
    cursor.execute(
        "SELECT src_paper_id, dst_paper_id, weight FROM graph_edge WHERE layer = ?",
        (EXPLORE_LAYER,),
    )
    links = [
        {"source": row[0], "target": row[1], "weight": row[2]}
        for row in cursor.fetchall()
    ]

    # clusters: exploration_id=1 scopes to the explore camps only -- library's
    # clusters use exploration_id IS NULL, a disjoint set from this filter.
    cursor.execute(
        """
        SELECT c.id, COALESCE(c.llm_label, c.label), COUNT(pc.paper_id)
        FROM cluster c
        JOIN paper_cluster pc ON pc.cluster_id = c.id
        WHERE c.exploration_id = ?
        GROUP BY c.id, c.label, c.llm_label
        """,
        (EXPLORE_EXPLORATION_ID,),
    )
    clusters = [
        {"id": row[0], "label": row[1], "size": row[2]}
        for row in cursor.fetchall()
    ]

    db.close()

    return {"nodes": nodes, "links": links, "clusters": clusters}


@router.get("/explore/synthesis")
async def get_explore_synthesis():
    db = connect(DB_PATH)
    cursor = db.cursor()

    # latest run for this exploration, newest by created_at (there's expected
    # to be exactly one from F4c, but this is robust to future re-runs that
    # don't replace-in-place).
    cursor.execute(
        """
        SELECT id, overview, n_camps, n_scattered, model, created_at
        FROM synthesis_run
        WHERE exploration_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (EXPLORE_EXPLORATION_ID,),
    )
    run_row = cursor.fetchone()

    if run_row is None:
        db.close()
        return {"synthesis": None}

    run_id, overview, n_camps, n_scattered, model, created_at = run_row

    cursor.execute(
        "SELECT cluster_id, theme, claims_json FROM synthesis_cluster "
        "WHERE run_id = ? ORDER BY cluster_id",
        (run_id,),
    )
    camps = [
        {"cluster_id": r[0], "theme": r[1], "claims": json.loads(r[2])}
        for r in cursor.fetchall()
    ]

    cursor.execute(
        "SELECT kind, text, cluster_ids_json FROM synthesis_toplevel_item "
        "WHERE run_id = ? ORDER BY id",
        (run_id,),
    )
    toplevel = [
        {"kind": r[0], "text": r[1], "cluster_ids": json.loads(r[2])}
        for r in cursor.fetchall()
    ]

    cursor.execute(
        """
        SELECT s.paper_id, s.reason, p.title
        FROM synthesis_scattered s
        JOIN paper p ON p.id = s.paper_id
        WHERE s.run_id = ?
        ORDER BY s.paper_id
        """,
        (run_id,),
    )
    scattered = [
        {"paper_id": r[0], "reason": r[1], "title": r[2]}
        for r in cursor.fetchall()
    ]

    cursor.execute(
        "SELECT cluster_id, paper_id FROM synthesis_cluster_member "
        "WHERE run_id = ? ORDER BY cluster_id, paper_id",
        (run_id,),
    )
    cluster_members: dict[int, list[int]] = {}
    for cluster_id, paper_id in cursor.fetchall():
        cluster_members.setdefault(cluster_id, []).append(paper_id)

    db.close()

    # Success shape is flat (run/camps/toplevel/scattered/cluster_members at
    # top level), per spec -- distinct from the {"synthesis": null} empty-case
    # flag above, which signals "no run exists" rather than shaping an empty run.
    return {
        "run": {
            "overview": overview,
            "n_camps": n_camps,
            "n_scattered": n_scattered,
            "model": model,
            "created_at": created_at,
        },
        "camps": camps,
        "toplevel": toplevel,
        "scattered": scattered,
        "cluster_members": cluster_members,
    }
