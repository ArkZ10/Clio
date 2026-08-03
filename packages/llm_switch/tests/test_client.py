import json

from llm_switch.client import ThinkStreamFilter, chat_url, headers, parse_ndjson_line, parse_sse_line
from llm_switch.payloads import parse_stream_event


# ---------------------------------------------------------------------------
# chat_url
# ---------------------------------------------------------------------------

def test_chat_url_deepseek_openai_compat():
    assert chat_url("https://api.deepseek.com", "openai") == "https://api.deepseek.com/v1/chat/completions"


def test_chat_url_base_ending_in_v1():
    assert chat_url("https://api.deepseek.com/v1", "openai") == "https://api.deepseek.com/v1/chat/completions"


def test_chat_url_ollama():
    assert chat_url("http://localhost:11434", "ollama") == "http://localhost:11434/api/chat"


def test_chat_url_anthropic():
    assert chat_url("https://api.anthropic.com", "anthropic") == "https://api.anthropic.com/v1/messages"


def test_chat_url_anthropic_base_ending_in_v1():
    assert chat_url("https://api.anthropic.com/v1", "anthropic") == "https://api.anthropic.com/v1/messages"


def test_chat_url_strips_trailing_slash():
    assert chat_url("http://localhost:11434/", "ollama") == "http://localhost:11434/api/chat"


# ---------------------------------------------------------------------------
# headers
# ---------------------------------------------------------------------------

def test_headers_openai_with_key():
    h = headers("openai", "sk-abc")
    assert h["Authorization"] == "Bearer sk-abc"
    assert h["Content-Type"] == "application/json"


def test_headers_openai_without_key():
    h = headers("openai", None)
    assert "Authorization" not in h


def test_headers_ollama_has_no_auth():
    h = headers("ollama", None)
    assert "Authorization" not in h
    assert "x-api-key" not in h


def test_headers_anthropic():
    h = headers("anthropic", "ak-abc")
    assert h["x-api-key"] == "ak-abc"
    assert h["anthropic-version"] == "2023-06-01"


# ---------------------------------------------------------------------------
# parse_sse_line / parse_ndjson_line
# ---------------------------------------------------------------------------

def test_parse_sse_line_data():
    assert parse_sse_line('data: {"x":1}') == {"x": 1}


def test_parse_sse_line_done():
    assert parse_sse_line("data: [DONE]") is None


def test_parse_sse_line_blank():
    assert parse_sse_line("") is None


def test_parse_sse_line_non_data():
    assert parse_sse_line("event: ping") is None


def test_parse_ndjson_line_valid():
    assert parse_ndjson_line('{"a": 1}') == {"a": 1}


def test_parse_ndjson_line_blank():
    assert parse_ndjson_line("   ") is None


# ---------------------------------------------------------------------------
# Stream framing end-to-end, fed canned lines through line_parser +
# parse_stream_event -- no network, no async.
# ---------------------------------------------------------------------------

def _drive(provider, lines, line_parser):
    events = []
    for line in lines:
        raw = line_parser(line)
        if raw is None:
            continue
        ev = parse_stream_event(provider, raw)
        if ev:
            events.append(ev)
    return events


def test_openai_sse_stream_framing_separates_reasoning_from_content():
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"let me think... "}}]}',
        'data: {"choices":[{"delta":{"content":"hello"}}]}',
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    events = _drive("openai", lines, parse_sse_line)

    assert events == [
        {"delta": "let me think... ", "thinking": True},
        {"delta": "hello"},
        {"delta": " world"},
        {"usage": {"prompt_tokens": 5, "completion_tokens": 2}},
    ]

    content_text = "".join(e["delta"] for e in events if "delta" in e and not e.get("thinking"))
    reasoning_text = "".join(e["delta"] for e in events if e.get("thinking"))

    assert content_text == "hello world"
    assert reasoning_text == "let me think... "
    assert "let me think" not in content_text


def test_ollama_ndjson_stream_framing():
    lines = [
        json.dumps({"message": {"content": "He"}, "done": False}),
        json.dumps({"message": {"content": "llo"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 4, "eval_count": 2}),
    ]
    events = _drive("ollama", lines, parse_ndjson_line)

    assert events == [
        {"delta": "He"},
        {"delta": "llo"},
        {"usage": {"prompt_tokens": 4, "completion_tokens": 2}},
    ]

    assembled = "".join(e["delta"] for e in events if "delta" in e)
    assert assembled == "Hello"


# ---------------------------------------------------------------------------
# ThinkStreamFilter -- stateful inline <think> filtering across chunk
# boundaries. Buffers until the first marker resolves whether text is
# reasoning or not (see the class docstring for the trade-off this implies).
# ---------------------------------------------------------------------------

def _drive_think_filter(chunks):
    f = ThinkStreamFilter()
    visible_total = ""
    thinking_total = ""
    for c in chunks:
        v, t = f.feed(c)
        visible_total += v
        thinking_total += t
    visible_total += f.flush()
    return visible_total, thinking_total


def test_think_filter_single_chunk_with_full_tags():
    visible, thinking = _drive_think_filter(["<think>plan</think>answer"])
    assert visible == "answer"
    assert thinking == "plan"


def test_think_filter_tags_split_across_chunks():
    visible, thinking = _drive_think_filter(["<th", "ink>plan</thi", "nk>answer"])
    assert visible == "answer"
    assert thinking == "plan"
    assert "<" not in visible and ">" not in visible


def test_think_filter_no_tags_content_passes_through_unchanged():
    # No marker ever appears, so everything is held in `pending` until
    # flush() -- the accepted buffer-until-resolved trade-off. Content must
    # still come through byte-for-byte once the stream ends.
    visible, thinking = _drive_think_filter(["Hello", ", ", "world", "!"])
    assert visible == "Hello, world!"
    assert thinking == ""


def test_think_filter_lone_closing_tag_split_across_chunks():
    chunks = ["We should answer pong", ".\n</th", "ink>\n\n", "pong"]
    visible, thinking = _drive_think_filter(chunks)
    assert visible == "\n\npong"
    assert thinking == "We should answer pong.\n"
    assert "</think>" not in visible
    assert "<think>" not in visible


def _apply_filter_to_events(events):
    """Mirrors stream()'s branching: only non-thinking-tagged delta events go
    through ThinkStreamFilter; everything else passes through unchanged."""
    filt = ThinkStreamFilter()
    out = []
    for ev in events:
        if "delta" in ev and not ev.get("thinking"):
            visible, reasoning = filt.feed(ev["delta"])
            if reasoning:
                out.append({"delta": reasoning, "thinking": True})
            if visible:
                out.append({"delta": visible})
        else:
            out.append(ev)
    trailing = filt.flush()
    if trailing:
        out.append({"delta": trailing})
    return out


def test_think_filter_does_not_double_filter_already_tagged_thinking_events():
    events = [
        {"delta": "raw native reasoning", "thinking": True},  # e.g. ollama's "thinking" field
        {"delta": "hello "},
        {"delta": "world"},
    ]
    out = _apply_filter_to_events(events)

    # Already-tagged event passes through completely unchanged.
    assert out[0] == {"delta": "raw native reasoning", "thinking": True}

    visible_text = "".join(e["delta"] for e in out if "delta" in e and not e.get("thinking"))
    assert visible_text == "hello world"


# ---------------------------------------------------------------------------
# ThinkStreamFilter latency fix: bounded lone-closer buffering (max_lone_buffer)
# so a tagless response streams incrementally instead of arriving all at once.
# ---------------------------------------------------------------------------

def test_think_filter_no_tag_long_stream_emits_incrementally_once_cap_exceeded():
    # Small cap so the test doesn't need literally thousands of characters.
    f = ThinkStreamFilter(max_lone_buffer=20)
    chunks = ["abcde"] * 10  # 50 chars total, no think tags at all
    visible_deltas_before_end = []
    visible_total = ""
    for c in chunks:
        v, t = f.feed(c)
        if v:
            visible_deltas_before_end.append(v)
        visible_total += v
        assert t == ""
    visible_total += f.flush()

    # The regression guard: output streamed in more than one piece before the
    # final flush -- it wasn't withheld until the very end.
    assert len(visible_deltas_before_end) > 1
    assert visible_total == "abcde" * 10


def test_think_filter_text_before_opening_tag_emitted_promptly():
    f = ThinkStreamFilter()
    v1, t1 = f.feed("Hello there. ")  # preamble, no tag yet -- still ambiguous
    assert v1 == ""
    assert t1 == ""

    # The tag arrives in the very next chunk: the preamble is released
    # immediately alongside it, not held until the cap or stream end.
    v2, t2 = f.feed("<think>reasoning here</think>answer")
    assert "Hello there." in v2
    assert "answer" in v2
    assert t2 == "reasoning here"


def test_think_filter_lone_closer_under_cap_still_classified_as_thinking():
    f = ThinkStreamFilter(max_lone_buffer=100)
    visible, thinking = f.feed("short reasoning</think>answer")
    visible += f.flush()
    assert thinking == "short reasoning"
    assert visible == "answer"


def test_think_filter_tagless_response_exceeding_cap_flushes_as_visible():
    f = ThinkStreamFilter(max_lone_buffer=20)
    text = "x" * 50  # no tags at all, well over the 20-char cap
    visible, thinking = f.feed(text)
    visible += f.flush()
    assert visible == text
    assert thinking == ""


def test_think_filter_lone_closer_over_cap_leaks_as_visible():
    # Document the accepted trade-off explicitly: once the cap trips, a
    # "</think>" that arrives afterward can no longer retroactively
    # reclassify text that was already flushed as visible.
    f = ThinkStreamFilter(max_lone_buffer=10)
    v1, t1 = f.feed("this reasoning text is long")  # > 10 chars, no tag yet
    v2, t2 = f.feed("</think>answer")
    total_visible = v1 + v2 + f.flush()
    assert "this reasoning text is long" in total_visible
    assert "answer" in total_visible
