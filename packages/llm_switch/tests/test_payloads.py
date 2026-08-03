from llm_switch import payloads


# ---------------------------------------------------------------------------
# sanitize_messages
# ---------------------------------------------------------------------------

def test_sanitize_messages_strips_reasoning_keys():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "secret plan",
            "thinking": "secret plan 2",
        },
    ]
    cleaned = payloads.sanitize_messages(messages)

    assert cleaned[0] == {"role": "user", "content": "hi"}
    assert cleaned[1] == {"role": "assistant", "content": "answer"}
    # original input must not be mutated
    assert "reasoning_content" in messages[1]
    assert "thinking" in messages[1]


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------

def test_build_request_openai_non_thinking_has_temperature():
    body = payloads.build_request(
        "openai",
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-chat",
        temperature=0.7,
        thinking=False,
    )
    assert body["temperature"] == 0.7
    assert "thinking" not in body
    assert "reasoning_effort" not in body


def test_build_request_openai_thinking_omits_temperature():
    body = payloads.build_request(
        "openai",
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-reasoner",
        temperature=0.7,
        thinking=True,
    )
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "medium"
    assert "temperature" not in body


def test_build_request_openai_includes_max_tokens_and_tools():
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    body = payloads.build_request(
        "openai",
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-x",
        max_tokens=512,
        tools=tools,
    )
    assert body["max_tokens"] == 512
    assert body["tools"] == tools


def test_build_request_openai_sanitizes_messages():
    body = payloads.build_request(
        "openai",
        messages=[{"role": "assistant", "content": "x", "reasoning_content": "y"}],
        model="gpt-x",
    )
    assert "reasoning_content" not in body["messages"][0]


def test_build_request_ollama_think_true():
    body = payloads.build_request(
        "ollama",
        messages=[{"role": "user", "content": "hi"}],
        model="qwen3:4b",
        thinking=True,
    )
    assert body["think"] is True
    assert body["model"] == "qwen3:4b"


def test_build_request_ollama_think_false_by_default():
    body = payloads.build_request(
        "ollama",
        messages=[{"role": "user", "content": "hi"}],
        model="qwen3:4b",
    )
    assert body["think"] is False


def test_build_request_ollama_options():
    body = payloads.build_request(
        "ollama",
        messages=[{"role": "user", "content": "hi"}],
        model="qwen3:4b",
        temperature=0.3,
        max_tokens=100,
    )
    assert body["options"]["temperature"] == 0.3
    assert body["options"]["num_predict"] == 100


def test_build_request_anthropic_defaults_max_tokens():
    body = payloads.build_request(
        "anthropic",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-x",
    )
    assert body["max_tokens"] == 4096


def test_build_request_anthropic_respects_explicit_max_tokens():
    body = payloads.build_request(
        "anthropic",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-x",
        max_tokens=1024,
    )
    assert body["max_tokens"] == 1024


def test_build_request_anthropic_extracts_system_message():
    body = payloads.build_request(
        "anthropic",
        messages=[
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
        ],
        model="claude-x",
    )
    assert body["system"] == "be nice"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_build_request_anthropic_thinking():
    body = payloads.build_request(
        "anthropic",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-x",
        thinking=True,
    )
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2048}


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------

def test_parse_response_openai_separates_reasoning_and_text():
    data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "the answer is 4",
                    "reasoning_content": "2 + 2 = 4",
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    result = payloads.parse_response("openai", data)
    assert result["text"] == "the answer is 4"
    assert result["reasoning"] == "2 + 2 = 4"
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_parse_response_openai_tool_calls_round_trip():
    tool_calls = [{"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}]
    data = {"choices": [{"message": {"content": None, "tool_calls": tool_calls}}]}
    result = payloads.parse_response("openai", data)
    assert result["tool_calls"] == tool_calls
    assert result["text"] == ""


def test_parse_response_ollama_strips_think_tags_from_content():
    data = {"message": {"content": "<think>plan</think>answer"}}
    result = payloads.parse_response("ollama", data)
    assert result["text"] == "answer"
    assert result["reasoning"] == "plan"


def test_parse_response_ollama_strips_lone_closing_think_tag():
    # Qwen3-via-Ollama: opening tag pre-seeded in the prompt, never appears
    # in the response -- only the model-generated closing tag does.
    data = {"message": {"content": "reasoning prose here\n</think>\n\npong"}}
    result = payloads.parse_response("ollama", data)
    assert result["text"] == "pong"
    assert "reasoning prose here" in result["reasoning"]
    assert "</think>" not in result["text"]


def test_parse_response_ollama_native_thinking_field():
    data = {"message": {"content": "answer", "thinking": "plan"}}
    result = payloads.parse_response("ollama", data)
    assert result["text"] == "answer"
    assert result["reasoning"] == "plan"


def test_parse_response_ollama_usage_from_eval_counts():
    data = {
        "message": {"content": "answer"},
        "prompt_eval_count": 12,
        "eval_count": 7,
    }
    result = payloads.parse_response("ollama", data)
    assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 7}


def test_parse_response_anthropic_splits_text_thinking_tool_use():
    data = {
        "content": [
            {"type": "thinking", "thinking": "let me think"},
            {"type": "text", "text": "here is the answer"},
            {"type": "tool_use", "id": "t1", "name": "lookup", "input": {}},
        ],
        "usage": {"input_tokens": 3, "output_tokens": 9},
    }
    result = payloads.parse_response("anthropic", data)
    assert result["text"] == "here is the answer"
    assert result["reasoning"] == "let me think"
    assert result["tool_calls"] == [{"type": "tool_use", "id": "t1", "name": "lookup", "input": {}}]
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 9}


# ---------------------------------------------------------------------------
# strip_think
# ---------------------------------------------------------------------------

def test_strip_think_basic():
    clean, reasoning = payloads.strip_think("<think>plan</think>answer")
    assert clean == "answer"
    assert reasoning == "plan"


def test_strip_think_no_tags_passthrough():
    clean, reasoning = payloads.strip_think("just an answer")
    assert clean == "just an answer"
    assert reasoning == ""


def test_strip_think_empty_string():
    clean, reasoning = payloads.strip_think("")
    assert clean == ""
    assert reasoning == ""


def test_strip_think_lone_closing_tag_no_opener():
    # Qwen3-via-Ollama pattern: the opening <think> is pre-seeded in the
    # prompt template and never reaches the API response -- only the
    # model-generated closing tag does.
    text = "We are asked to reply with pong.\nSo the answer is pong.\n</think>\n\npong"
    clean, reasoning = payloads.strip_think(text)
    assert clean == "pong"
    assert reasoning == "We are asked to reply with pong.\nSo the answer is pong.\n"
    assert "</think>" not in clean


def test_strip_think_well_formed_pair_takes_precedence():
    # A well-formed pair should still be stripped normally even though the
    # lone-closing-tag pattern also matches on a "</think>" substring.
    clean, reasoning = payloads.strip_think("<think>plan</think>answer")
    assert clean == "answer"
    assert reasoning == "plan"


# ---------------------------------------------------------------------------
# parse_stream_event
# ---------------------------------------------------------------------------

def test_parse_stream_event_openai_reasoning_delta():
    chunk = {"choices": [{"delta": {"reasoning_content": "thinking..."}}]}
    event = payloads.parse_stream_event("openai", chunk)
    assert event == {"delta": "thinking...", "thinking": True}


def test_parse_stream_event_openai_content_delta():
    chunk = {"choices": [{"delta": {"content": "hello"}}]}
    event = payloads.parse_stream_event("openai", chunk)
    assert event == {"delta": "hello"}


def test_parse_stream_event_openai_tool_calls_delta():
    tc = [{"index": 0, "function": {"name": "lookup"}}]
    chunk = {"choices": [{"delta": {"tool_calls": tc}}]}
    event = payloads.parse_stream_event("openai", chunk)
    assert event == {"tool_calls": tc}


def test_parse_stream_event_openai_usage_chunk():
    chunk = {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
    event = payloads.parse_stream_event("openai", chunk)
    assert event == {"usage": {"prompt_tokens": 5, "completion_tokens": 1}}


def test_parse_stream_event_openai_empty_chunk_is_none():
    chunk = {"choices": [{"delta": {}}]}
    assert payloads.parse_stream_event("openai", chunk) is None


def test_parse_stream_event_ollama_content_chunk():
    chunk = {"message": {"content": "hel"}, "done": False}
    event = payloads.parse_stream_event("ollama", chunk)
    assert event == {"delta": "hel"}


def test_parse_stream_event_ollama_thinking_chunk():
    chunk = {"message": {"thinking": "pondering"}, "done": False}
    event = payloads.parse_stream_event("ollama", chunk)
    assert event == {"delta": "pondering", "thinking": True}


def test_parse_stream_event_ollama_done_chunk_yields_usage():
    chunk = {"message": {"content": ""}, "done": True, "prompt_eval_count": 8, "eval_count": 3}
    event = payloads.parse_stream_event("ollama", chunk)
    assert event == {"usage": {"prompt_tokens": 8, "completion_tokens": 3}}


def test_parse_stream_event_anthropic_text_delta():
    chunk = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
    event = payloads.parse_stream_event("anthropic", chunk)
    assert event == {"delta": "hi"}


def test_parse_stream_event_anthropic_thinking_delta():
    chunk = {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}}
    event = payloads.parse_stream_event("anthropic", chunk)
    assert event == {"delta": "hmm", "thinking": True}


def test_parse_stream_event_anthropic_message_delta_usage():
    chunk = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 15}}
    event = payloads.parse_stream_event("anthropic", chunk)
    assert event == {"usage": {"output_tokens": 15}}
