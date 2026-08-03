"""LLM relevance scoring over retrieved arXiv papers.

Scores ONLY -- no DB writes, no persistence. The point of this step is the
1:1 validation: a rerank whose output doesn't map exactly onto the real input
papers is worthless, so a bad mapping fails loud rather than silently
defaulting or fabricating.

The model sees only a stable 1..N index per paper, never the arxiv_id, so it
can't invent a plausible-looking ID -- an invented index is caught by
validation instead.
"""
import json
import re

import llm_switch
from backend.routing import resolve_stage

_FIRST_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You rank research papers by relevance to a query. For EVERY paper given, "
    "output a relevance score 0-10 (10=directly on-topic, 0=unrelated) and a "
    "one-sentence reason. Respond with ONLY this JSON, no prose, no markdown: "
    '{"rankings":[{"index":<int>,"score":<int 0-10>,"reason":"<one sentence>"}, '
    "...]}. Include EXACTLY one entry per paper given."
)


class RerankValidationError(Exception):
    """The model's response did not map 1:1 onto the input papers."""


def _build_messages(query: str, papers: list) -> list[dict]:
    lines = [f"Query: {query}", "", "Papers:"]
    for i, p in enumerate(papers, start=1):
        lines.append(f"{i}. {p.title}\n{p.abstract}\n")
    # Pin the index convention explicitly: the numbers below are 1..N and the
    # model must echo those exact numbers (DeepSeek otherwise defaults to
    # 0-based, which fails the strict 1..N validation).
    lines.append(
        f"\nUse the exact number shown before each paper as its \"index\". "
        f"Indices run from 1 to {len(papers)}. Do not start at 0. "
        f"Output exactly {len(papers)} entries, one per paper."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _extract_json(raw: str) -> dict:
    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    match = _FIRST_JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    raise RerankValidationError(f"Could not parse JSON from model response: {raw[:200]!r}")


def _validate(rankings: list, n: int) -> dict[int, dict]:
    """Enforce exactly-one-entry-per-input, indices in 1..N, scores in [0,10].
    Returns {index: {score, reason}}. Raises RerankValidationError naming the
    specific missing / extra / out-of-range indices."""
    expected = set(range(1, n + 1))
    seen = {}
    extra = []
    duplicates = []
    bad_score = []

    for entry in rankings:
        idx = entry.get("index")
        score = entry.get("score")
        if not isinstance(idx, int) or idx < 1 or idx > n:
            extra.append(idx)
            continue
        if idx in seen:
            duplicates.append(idx)
            continue
        if not isinstance(score, (int, float)) or not (0 <= score <= 10):
            bad_score.append((idx, score))
            continue
        seen[idx] = {"score": float(score), "reason": entry.get("reason", "")}

    missing = sorted(expected - set(seen.keys()))

    problems = []
    if missing:
        problems.append(f"missing indices: {missing}")
    if extra:
        problems.append(f"out-of-range/invalid indices: {extra}")
    if duplicates:
        problems.append(f"duplicate indices: {duplicates}")
    if bad_score:
        problems.append(f"out-of-range scores: {bad_score}")

    if problems:
        raise RerankValidationError(
            f"rerank validation failed for {n} input papers -- " + "; ".join(problems)
        )

    return seen


async def rerank(query: str, papers: list) -> list:
    """Score each paper's relevance to the query via the routed LLM, validate
    a strict 1:1 mapping back to the inputs, and return them sorted by score
    descending. Each returned paper carries `.score` and `.reason`.

    Raises RerankValidationError if the model's response doesn't map exactly
    onto the input papers -- never fabricates or defaults."""
    n = len(papers)
    if n == 0:
        return []

    messages = _build_messages(query, papers)
    endpoint = resolve_stage("rerank")
    # ~50-70 tokens per entry once a full-sentence reason is included; 60*N
    # truncated the JSON in practice, so budget more generously.
    max_tokens = min(120 * n, 8000)

    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=max_tokens
    )

    obj = _extract_json(result.text)
    rankings = obj.get("rankings")
    if not isinstance(rankings, list):
        raise RerankValidationError(
            f"response has no 'rankings' list: {result.text[:200]!r}"
        )

    scored = _validate(rankings, n)

    ranked = []
    for i, p in enumerate(papers, start=1):
        p.score = scored[i]["score"]
        p.reason = scored[i]["reason"]
        ranked.append(p)

    ranked.sort(key=lambda p: p.score, reverse=True)
    return ranked
