"""LLM-generated cluster labels. The first real LLM job in the app.

Writes to cluster.llm_label, never to cluster.label -- the numeric placeholder
("Cluster 0") stays put as a fallback in case a label is missing or a bad run
produced garbage.

Two prior attempts asked qwen3:4b (local) for a prose label and post-processed
the response (first-line, then last-line + a reasoning-marker blocklist).
Both failed the same way: the model rambled past any token budget we gave it
and never reached an answer, regardless of prompt shape (plain text, JSON,
one-shot example). The JSON-parsing approach (parse_label below) is solid --
failures reject to a clean None rather than writing garbage -- but the model
itself was the bottleneck, not the parsing. This stage now routes to deepseek
instead, with titles AND abstracts as context (DeepSeek's reasoning is
already cleanly separated into CallResult.reasoning, never .text, so a small
model's tendency to ramble into the visible answer isn't a risk here).
"""
import json
import re

import llm_switch
from backend.config import DB_PATH
from backend.db import connect, init_db
from backend.routing import resolve_stage

MAX_TITLES = 20
MAX_LABEL_LEN = 60

SYSTEM_PROMPT = (
    "You label clusters of research papers. Respond with ONLY a JSON object "
    'of the exact shape {"label": "<short topic label, at most 5 words>"} '
    "and nothing else -- no preamble, no explanation, no markdown, no code "
    "fences."
)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_FIRST_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_SURROUNDING_QUOTES_RE = re.compile(r'^[\'"`]+|[\'"`]+$')


def parse_label(raw: str) -> str | None:
    """Parse the model's JSON response and extract the label field. Returns
    None on any parse failure or invalid/missing/over-length label -- the
    caller should leave llm_label NULL rather than write a guess."""
    if not raw:
        return None

    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()

    obj = _try_parse_json(text)
    if obj is None:
        # qwen3 may wrap the JSON in stray prose even when asked not to --
        # fall back to locating the first {...} substring.
        match = _FIRST_JSON_OBJECT_RE.search(text)
        if match:
            obj = _try_parse_json(match.group(0))

    if not isinstance(obj, dict):
        return None

    label = obj.get("label")
    if not isinstance(label, str):
        return None

    label = _SURROUNDING_QUOTES_RE.sub("", label.strip()).strip()
    if not label:
        return None
    if len(label) > MAX_LABEL_LEN:
        return None

    return label


def _try_parse_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _fetch_cluster_ids(cursor) -> list[int]:
    cursor.execute(
        "SELECT id FROM cluster WHERE exploration_id IS NULL AND id != -1 ORDER BY id"
    )
    return [row[0] for row in cursor.fetchall()]


def _fetch_member_papers(cursor, cluster_id: int) -> list[tuple[str, str | None]]:
    """(title, abstract) pairs for cluster members, ordered by paper_id,
    capped at MAX_TITLES."""
    cursor.execute(
        "SELECT paper_id FROM paper_cluster WHERE cluster_id = ? ORDER BY paper_id ASC",
        (cluster_id,),
    )
    paper_ids = [row[0] for row in cursor.fetchall()][:MAX_TITLES]
    if not paper_ids:
        return []

    placeholders = ",".join("?" * len(paper_ids))
    cursor.execute(
        f"SELECT id, title, abstract FROM paper WHERE id IN ({placeholders})", paper_ids
    )
    paper_by_id = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    return [paper_by_id[pid] for pid in paper_ids if pid in paper_by_id]


_EXAMPLE_USER_PROMPT = (
    "Papers in this cluster:\n"
    "1. Title: Deep Residual Learning for Image Recognition\n"
    "   Abstract: We present a residual learning framework that eases the "
    "training of substantially deeper convolutional networks for image "
    "recognition, using skip connections to address the degradation problem.\n"
    "2. Title: ImageNet Classification with Deep Convolutional Neural Networks\n"
    "   Abstract: We trained a large deep convolutional neural network to "
    "classify 1.2 million high-resolution images from ImageNet into 1000 "
    "classes, achieving substantially better results than previous approaches.\n"
    "\nLabel:"
)
_EXAMPLE_ASSISTANT_REPLY = '{"label": "Image Classification"}'


def _build_messages(papers: list[tuple[str, str | None]]) -> list[dict]:
    entries = []
    for i, (title, abstract) in enumerate(papers, start=1):
        entry = f"{i}. Title: {title}"
        if abstract:
            entry += f"\n   Abstract: {abstract}"
        entries.append(entry)
    papers_block = "\n".join(entries)
    user_prompt = f"Papers in this cluster:\n{papers_block}\n\nLabel:"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        # One-shot example (off-domain on purpose -- computer vision, not
        # diffusion/safety/LLM): if the model parrots "Image Classification"
        # back on an unrelated cluster, that's visibly wrong rather than
        # silently plausible.
        {"role": "user", "content": _EXAMPLE_USER_PROMPT},
        {"role": "assistant", "content": _EXAMPLE_ASSISTANT_REPLY},
        {"role": "user", "content": user_prompt},
    ]


async def label_clusters() -> list[dict]:
    """Label every real (non-exploration, non-noise) cluster. Returns a report
    list of {cluster_id, member_count, titles, llm_label} for inspection."""
    init_db(DB_PATH)
    db = connect(DB_PATH)
    cursor = db.cursor()

    cluster_ids = _fetch_cluster_ids(cursor)
    endpoint = resolve_stage("cluster_label")

    report = []
    for cluster_id in cluster_ids:
        papers = _fetch_member_papers(cursor, cluster_id)
        titles = [title for title, _ in papers]

        cursor.execute("SELECT COUNT(*) FROM paper_cluster WHERE cluster_id = ?", (cluster_id,))
        member_count = cursor.fetchone()[0]

        llm_label = None
        raw_text = None
        if papers:
            messages = _build_messages(papers)
            # llm_switch's build_request has no format/JSON-mode passthrough
            # (checked -- closed kwarg signature, no **kwargs), so there's no
            # decode-level enforcement here; we rely on the prompt + parsing.
            # deepseek's reasoning lands in CallResult.reasoning, never .text,
            # so a big budget funds reasoning safely without risking a
            # rambling preamble leaking into the visible answer.
            result = await llm_switch.call(
                messages, endpoint.name, thinking=False, max_tokens=2000
            )
            raw_text = result.text
            llm_label = parse_label(raw_text)

        cursor.execute(
            "UPDATE cluster SET llm_label = ? WHERE id = ?", (llm_label, cluster_id)
        )
        db.commit()

        report.append(
            {
                "cluster_id": cluster_id,
                "member_count": member_count,
                "titles": titles,
                "raw_text": raw_text,
                "llm_label": llm_label,
            }
        )

    db.close()
    return report
