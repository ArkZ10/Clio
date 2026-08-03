import json

from fastapi import APIRouter, HTTPException

from backend.config import DB_PATH
from backend.db import connect

# No router-level prefix: this router serves both /library/* and /paper/{id},
# so each route declares its own full path instead.
router = APIRouter()


@router.get("/library/graph")
async def get_graph():
    db = connect(DB_PATH)
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT p.id, p.title, pc.cluster_id
        FROM paper p
        LEFT JOIN paper_cluster pc ON pc.paper_id = p.id
        WHERE p.source = 'library'
        """
    )
    nodes = [
        {"id": row[0], "title": row[1], "cluster": row[2] if row[2] is not None else -1}
        for row in cursor.fetchall()
    ]

    cursor.execute(
        "SELECT src_paper_id, dst_paper_id, weight FROM graph_edge WHERE layer = 'semantic'"
    )
    links = [
        {"source": row[0], "target": row[1], "weight": row[2]}
        for row in cursor.fetchall()
    ]

    cursor.execute(
        """
        SELECT c.id, COALESCE(c.llm_label, c.label), COUNT(pc.paper_id)
        FROM cluster c
        JOIN paper_cluster pc ON pc.cluster_id = c.id
        WHERE c.exploration_id IS NULL
        GROUP BY c.id, c.label, c.llm_label
        """
    )
    clusters = [
        {"id": row[0], "label": row[1], "size": row[2]}
        for row in cursor.fetchall()
    ]

    db.close()

    return {"nodes": nodes, "links": links, "clusters": clusters}


@router.get("/paper/{paper_id}")
async def get_paper(paper_id: int):
    db = connect(DB_PATH)
    cursor = db.cursor()

    cursor.execute(
        "SELECT id, title, abstract, authors, year, needs_review, pdf_path "
        "FROM paper WHERE id = ?",
        (paper_id,),
    )
    row = cursor.fetchone()
    db.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    id_, title, abstract, authors_raw, year, needs_review, pdf_path = row
    authors = json.loads(authors_raw) if authors_raw else []

    return {
        "id": id_,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": year,
        "needs_review": needs_review,
        "pdf_path": pdf_path,
    }
