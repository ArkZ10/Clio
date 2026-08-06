"""Index-first retrieval + grounded answering over the vault.

Two LLM steps:
  1. select_pages -- show the model index.md, ask which pages are needed. An
     empty list means "this wiki doesn't cover that".
  2. answer / answer_stream -- send those pages' full text, ask for an answer
     citing them. answer_stream is the same call streamed token-by-token.

Coverage is a model judgement, not a deterministic check, so anti-fabrication
rests on two guards:
  Guard 1 -- empty selection. answer() short-circuits, no LLM call.
  Guard 2 -- selection over-picks loosely-related pages instead of []. The
    answer prompt asks for a leading `COVERAGE: YES/NO` line (see
    ANSWER_SYSTEM_PROMPT); _split_coverage_header parses and strips it before
    any caller sees it. No extra LLM call, rides the same request. Fails open
    (did_answer=True) if the model doesn't emit the header -- a missed signal
    should never turn a real answer into a false "not covered".

Read-only: never writes to the vault.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

import llm_switch
from backend.routing import resolve_stage
from backend.vault import scan_vault, split_frontmatter

INDEX_STEM = "index"
MAX_PAGES = 8
SELECT_MAX_TOKENS = 4000
ANSWER_MAX_TOKENS = 8000
MAX_HISTORY_TURNS = 6

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
# rerank.py's _extract_json only recovers objects ({.*}), not this step's array.
_FIRST_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
# The answer step's leading "COVERAGE: YES/NO\n---\n" header. Anchored to the
# start so it can't fire on "coverage" appearing in prose.
_COVERAGE_HEADER_RE = re.compile(r"\A\s*COVERAGE:\s*(YES|NO)\s*\n-{3,}\s*\n?", re.IGNORECASE)
# answer_stream buffers deltas up to this many chars while waiting for the
# header to resolve, well past its ~20-char expected length -- past that with
# no match, it gives up and streams what's buffered (same fail-open as the
# non-streaming path), so a header-less response still streams promptly
# instead of silently waiting for the whole thing.
_HEADER_BUFFER_CAP = 80

SELECT_PROMPT = """\
Here is the index of a personal research wiki. Each entry is a page with a
one-line summary.

{index}

The user asks: {question}

Return ONLY a JSON array of the page names (exact stems from the index) needed
to answer. Return AT MOST {max_pages}.
If the index contains NOTHING relevant to this question, return an empty array [].
Do NOT return loosely-related pages to be helpful -- an empty array is the
correct, expected answer when the wiki does not cover the topic.
Output strictly the JSON array, no prose, no fences.\
"""

ANSWER_SYSTEM_PROMPT = """\
Answer using ONLY the wiki pages provided below. Cite the page names you used,
inline, as [[Page Name]].
If the provided pages do not actually contain the answer, say so plainly rather
than inferring. Do not use outside knowledge as if it were from the wiki; if you
add context from general knowledge, label it clearly as outside the wiki.

Before your answer, output ONE line stating whether the provided pages actually
contain the answer, in EXACTLY this form (nothing else on that line):
COVERAGE: YES
or
COVERAGE: NO
Then a line containing exactly --- on its own, then your answer.
Use COVERAGE: NO whenever the pages do not actually answer the question -- even
if you still write something explaining what the pages DO cover instead. Only
use COVERAGE: YES when your answer genuinely comes from the provided pages.\
"""

class SelectionFailed(Exception):
    """Selection returned nothing usable twice (empty or unparseable). NOT the
    same as an empty selection -- "not covered" and "the call broke" are
    different facts, and collapsing them would report a broken call as a
    confident "not in your wiki"."""


NO_COVERAGE_ANSWER = (
    "This wiki has no page covering that. Nothing in the index is relevant to "
    "the question, so there is no grounded answer to give -- and rather than "
    "synthesise one from general knowledge, this is being reported as a gap.\n\n"
    "To get an answer here, ingest a source on the topic so the wiki has "
    "something to reason from."
)


def load_records(vault_path) -> dict[str, dict]:
    """{stem: record} for the whole vault, one scan. find_page() rescans per
    call, so resolving N pages that way would mean N scans -- callers scan
    once and pass this map down instead."""
    return {r["stem"]: r for r in scan_vault(vault_path)}


def page_body(record: dict) -> str:
    """A page's markdown minus its YAML frontmatter."""
    _meta, body = split_frontmatter(record["text"])
    return body


def _extract_json_array(raw: str) -> list | None:
    """Parse a JSON array out of a model response, or None."""
    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    match = _FIRST_JSON_ARRAY_RE.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _split_coverage_header(raw: str) -> tuple[bool, str]:
    """(did_answer, clean_text) -- strips the leading COVERAGE header so
    callers only see clean prose. Fails open: no header means did_answer=True,
    raw text unchanged -- a parsing miss must never fake "not covered"."""
    match = _COVERAGE_HEADER_RE.match(raw)
    if not match:
        return True, raw.strip()
    did_answer = match.group(1).upper() == "YES"
    return did_answer, raw[match.end():].strip()


async def _call_select(question: str, index_body: str) -> list | None:
    """One selection call. Returns the parsed array, or None if unusable."""
    prompt = SELECT_PROMPT.format(
        index=index_body, question=question, max_pages=MAX_PAGES
    )
    endpoint = resolve_stage("chat")
    result = await llm_switch.call(
        [{"role": "user", "content": prompt}],
        endpoint.name,
        thinking=False,
        max_tokens=SELECT_MAX_TOKENS,
    )
    if not result.text.strip():
        return None
    return _extract_json_array(result.text)


async def select_pages(question: str, records: dict[str, dict]) -> tuple[list[str], int]:
    """(stems, dropped_count) -- which vault pages are needed to answer. An
    empty list is a legitimate result. Stems that don't resolve to a real page
    (hallucinated names) are dropped and counted.

    Raises SelectionFailed if the call yields nothing usable -- an error, not
    a "no coverage" answer.
    """
    index_record = records.get(INDEX_STEM)
    if index_record is None:
        raise SelectionFailed(
            f"The vault has no '{INDEX_STEM}.md' page, so there is nothing to "
            "retrieve against."
        )

    index_body = page_body(index_record)

    raw = await _call_select(question, index_body)
    if raw is None:
        raw = await _call_select(question, index_body)  # one retry
        if raw is None:
            raise SelectionFailed(
                "The page-selection step returned nothing usable twice "
                "(empty or unparseable response)."
            )

    stems: list[str] = []
    dropped = 0
    for item in raw:
        if not isinstance(item, str):
            dropped += 1
            continue
        stem = item.strip()
        # Tolerate the model wrapping a name in [[ ]] despite being asked not to.
        if stem.startswith("[[") and stem.endswith("]]"):
            stem = stem[2:-2].strip()
        if stem in records:
            if stem not in stems:
                stems.append(stem)
        else:
            dropped += 1

    return stems[:MAX_PAGES], dropped


def _history_messages(history: list[dict] | None) -> list[dict]:
    """Recent turns as chat messages. Used only for answering -- selection
    always runs on the current question alone."""
    if not history:
        return []
    messages = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


def _build_answer_messages(
    question: str, stems: list[str], records: dict[str, dict], history: list[dict] | None
) -> list[dict] | None:
    """The messages for the answer call, or None if none of `stems` resolved
    to a real record (shouldn't happen -- select_pages already validates
    against records -- but Guard 1 covers it either way)."""
    blocks = []
    for stem in stems:
        record = records.get(stem)
        if record is None:
            continue
        blocks.append(f"### {stem}\n\n{page_body(record)}")
    if not blocks:
        return None

    pages_text = "\n\n---\n\n".join(blocks)
    user_content = f"Wiki pages:\n\n{pages_text}\n\n---\n\nQuestion: {question}"
    return [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": user_content},
    ]


EMPTY_RESPONSE_ANSWER = (
    "The model returned an empty response. The pages below were "
    "retrieved but not summarised -- try asking again."
)


async def answer(
    question: str,
    stems: list[str],
    records: dict[str, dict],
    history: list[dict] | None = None,
) -> tuple[str, list[str], bool]:
    """(answer_text, cited_pages, did_answer).

    Guard 1: no pages selected -> fixed response, no LLM call, did_answer=False.
    Guard 2: pages selected -> did_answer reflects the model's own COVERAGE
    judgement on this same call. False means cited_pages is emptied too --
    nothing was genuinely grounded.
    """
    if not stems:
        return NO_COVERAGE_ANSWER, [], False

    messages = _build_answer_messages(question, stems, records, history)
    if messages is None:
        return NO_COVERAGE_ANSWER, [], False

    endpoint = resolve_stage("chat")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=ANSWER_MAX_TOKENS
    )

    did_answer, text = _split_coverage_header(result.text)
    if not text:
        # Empty response is a hiccup, not a coverage judgement.
        text = EMPTY_RESPONSE_ANSWER
        did_answer = True

    # cited_pages is the set actually sent, not scraped from prose -- but only
    # when the model says it used them.
    cited = [stem for stem in stems if stem in records] if did_answer else []
    return text, cited, did_answer


async def answer_stream(
    question: str,
    stems: list[str],
    records: dict[str, dict],
    history: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """Streaming counterpart to answer(). Yields, in order:
      {"type": "coverage", "no_coverage": bool, "cited_pages": [...]} -- once,
        before any text. Resolved instantly for Guard 1 (no pages); for
        Guard 2, only once the COVERAGE header is seen or _HEADER_BUFFER_CAP
        is hit, so the caller knows how to style the reply before any of it
        is visible.
      {"type": "delta", "text": "..."} -- zero or more, the answer itself,
        with the COVERAGE header never included.
      {"type": "done"} -- once, last.
    """
    if not stems:
        yield {"type": "coverage", "no_coverage": True, "cited_pages": []}
        yield {"type": "delta", "text": NO_COVERAGE_ANSWER}
        yield {"type": "done"}
        return

    messages = _build_answer_messages(question, stems, records, history)
    if messages is None:
        yield {"type": "coverage", "no_coverage": True, "cited_pages": []}
        yield {"type": "delta", "text": NO_COVERAGE_ANSWER}
        yield {"type": "done"}
        return

    endpoint = resolve_stage("chat")

    buffer = ""
    header_resolved = False
    async for event in llm_switch.stream(
        messages, endpoint.name, thinking=False, max_tokens=ANSWER_MAX_TOKENS
    ):
        if event.get("thinking"):
            continue  # reasoning never reaches the caller
        delta = event.get("delta")
        if not delta:
            continue

        if header_resolved:
            yield {"type": "delta", "text": delta}
            continue

        buffer += delta
        match = _COVERAGE_HEADER_RE.match(buffer)
        if match:
            did_answer = match.group(1).upper() == "YES"
            header_resolved = True
            yield {
                "type": "coverage",
                "no_coverage": not did_answer,
                "cited_pages": stems if did_answer else [],
            }
            remainder = buffer[match.end():]
            if remainder:
                yield {"type": "delta", "text": remainder}
            buffer = ""
        elif len(buffer) > _HEADER_BUFFER_CAP:
            # Fail open, same as _split_coverage_header: no header showed up
            # in a reasonable window, so treat everything buffered as a real
            # answer and stop waiting.
            header_resolved = True
            yield {"type": "coverage", "no_coverage": False, "cited_pages": stems}
            yield {"type": "delta", "text": buffer}
            buffer = ""

    if not header_resolved:
        # Stream ended before ever resolving -- a short header-less reply, or
        # a genuinely empty response. Fails open either way.
        yield {"type": "coverage", "no_coverage": False, "cited_pages": stems}
        yield {"type": "delta", "text": buffer if buffer else EMPTY_RESPONSE_ANSWER}

    yield {"type": "done"}
