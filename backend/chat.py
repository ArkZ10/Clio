"""Index-first retrieval + grounded answering over the vault.

Two LLM steps:
  1. select_pages -- show the model `index.md` (the wiki's own catalog) and ask
     which pages are needed. This is ALSO where coverage is decided: returning
     an empty list is the model saying "this wiki doesn't cover that".
  2. answer -- send those pages' full text and ask for an answer citing them.

WHO DECIDES COVERAGE: the model, in step 1. There is no deterministic check for
"does this wiki cover X" -- that is a semantic judgement. So anti-fabrication
rests on two guards, both prompt-mediated:

  Guard 1 (empty selection) -- if step 1 returns [], answer() short-circuits and
    never calls the LLM. Deterministic GIVEN [], but reaching [] was a model
    decision.
  Guard 2 (over-selection) -- the likelier failure is the model being helpful
    and returning loosely-related pages instead of []. Guard 1 does nothing
    there; the answer prompt's "say so plainly rather than inferring" clause is
    the only defence.

KNOWN LIMITATION (V2): `no_coverage` reflects only the empty-selection case. If
step 1 over-selects and step 2 hedges, the response still reads no_coverage=false
with pages cited. Surfacing that properly needs a second-pass coverage signal
from step 2, which is out of scope here -- selected_pages/dropped_count are
returned so the gap is at least inspectable.

Read-only: this module never writes to the vault.
"""
from __future__ import annotations

import json
import re

import llm_switch
from backend.routing import resolve_stage
from backend.vault import scan_vault, split_frontmatter

INDEX_STEM = "index"
MAX_PAGES = 8
# Budgets must cover REASONING, not just the visible output. deepseek-v4-flash
# emits reasoning tokens even at thinking=False, and they count against
# max_tokens -- at 600 the model spent all 600 reasoning and returned an EMPTY
# string, which then looked like "no coverage". The selection output itself is a
# tiny JSON array; this budget is almost entirely headroom for reasoning.
SELECT_MAX_TOKENS = 4000
ANSWER_MAX_TOKENS = 8000
# Only the last few turns; enough for "what about the second one?" without
# letting a long transcript crowd out the actual page content.
MAX_HISTORY_TURNS = 6

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
# An ARRAY regex. backend/explore/rerank.py's _extract_json falls back on
# r"\{.*\}" (an object), so it cannot recover the list this step returns --
# hence a local parser rather than reusing that helper.
_FIRST_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

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
add context from general knowledge, label it clearly as outside the wiki.\
"""

class SelectionFailed(Exception):
    """The selection step produced nothing usable (empty or unparseable twice).

    Deliberately NOT the same as an empty selection. "The model judged that the
    wiki doesn't cover this" and "the call broke" are completely different
    facts, and collapsing them would make the system report a confident
    "not in your wiki" whenever the LLM hiccuped -- the precise dishonesty this
    feature exists to avoid. Callers surface this as an error, not as coverage.
    """


NO_COVERAGE_ANSWER = (
    "This wiki has no page covering that. Nothing in the index is relevant to "
    "the question, so there is no grounded answer to give -- and rather than "
    "synthesise one from general knowledge, this is being reported as a gap.\n\n"
    "To get an answer here, ingest a source on the topic so the wiki has "
    "something to reason from."
)


def load_records(vault_path) -> dict[str, dict]:
    """{stem: record} for the whole vault, from a SINGLE scan.

    scan_vault() re-reads every file and find_page() calls it internally, so
    resolving N pages via find_page would mean N full vault scans. Callers scan
    once per request and pass this map down.
    """
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
    """(stems, dropped_count) -- which vault pages are needed to answer.

    An empty list is a legitimate, expected result: the model judging that the
    wiki does not cover this. Stems that don't resolve to a real page are
    dropped (the model inventing page names) and counted.

    Raises SelectionFailed if the call yields nothing usable -- that is an
    error, never a "no coverage" answer.
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
        raw = await _call_select(question, index_body)  # one retry, per house idiom
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
    """Recent turns as chat messages.

    Used ONLY for answering -- page selection always runs on the current
    question alone, so history can never bias retrieval or smuggle in coverage.
    """
    if not history:
        return []
    messages = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


async def answer(
    question: str,
    stems: list[str],
    records: dict[str, dict],
    history: list[dict] | None = None,
) -> tuple[str, list[str]]:
    """(answer_text, cited_pages).

    GUARD 1: with no pages selected, this returns a fixed response and never
    calls the LLM -- there is nothing to ground an answer in, so none is
    generated. Note this only fires on a decision select_pages already made.
    """
    if not stems:
        return NO_COVERAGE_ANSWER, []

    blocks = []
    for stem in stems:
        record = records.get(stem)
        if record is None:
            continue
        blocks.append(f"### {stem}\n\n{page_body(record)}")
    if not blocks:
        return NO_COVERAGE_ANSWER, []

    pages_text = "\n\n---\n\n".join(blocks)
    user_content = f"Wiki pages:\n\n{pages_text}\n\n---\n\nQuestion: {question}"

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": user_content},
    ]
    endpoint = resolve_stage("chat")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=ANSWER_MAX_TOKENS
    )

    text = result.text.strip()
    if not text:
        text = (
            "The model returned an empty response. The pages below were "
            "retrieved but not summarised -- try asking again."
        )
    # cited_pages is the set actually SENT, so citations are structured server
    # data rather than regex-scraped out of the model's prose.
    cited = [stem for stem in stems if stem in records]
    return text, cited
