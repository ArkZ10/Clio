"""HTTP client: call() and stream(), wiring payloads.py's pure functions to httpx.

This is the only module in the package that touches the network.
"""
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

from . import get_endpoint, resolve_api_key
from .errors import LLMError
from .payloads import build_request, parse_response, parse_stream_event


@dataclass
class CallResult:
    text: str
    reasoning: str
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def chat_url(base_url: str, provider: str) -> str:
    base = base_url.rstrip("/")
    if provider == "ollama":
        return base + "/api/chat"
    if provider == "anthropic":
        return base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    # "openai" (covers DeepSeek, vLLM, LM Studio, OpenAI)
    return base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")


def headers(provider: str, api_key: Optional[str]) -> dict:
    if provider == "anthropic":
        return {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    if provider == "ollama":
        return {"Content-Type": "application/json"}
    # "openai"
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


DEFAULT_MAX_LONE_BUFFER = 2000


class ThinkStreamFilter:
    """Separates inline <think>...</think> reasoning from visible text across
    stream chunk boundaries (a per-chunk regex can't see a tag split across
    two deltas). Also handles a lone "</think>" with no opener -- some chat
    templates (Qwen3 via Ollama) pre-seed the opener in the prompt, so only
    the closer reaches the API.

    `buffer` holds back the last <=8 chars in case they're a split marker.
    `pending` holds text before the first marker is ever seen, since a later
    lone "</think>" would retroactively make it reasoning and an already-
    emitted visible chunk can't be un-emitted. Once a marker resolves that
    ambiguity, `pending` clears and emission is immediate from then on. If
    `pending` outgrows `max_lone_buffer` with no marker at all, it's released
    as visible -- caps worst-case latency for non-thinking models.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self, max_lone_buffer: int = DEFAULT_MAX_LONE_BUFFER):
        self.in_think = False
        self.buffer = ""
        self.resolved = False  # has any marker been seen yet?
        self.pending = ""
        self.max_lone_buffer = max_lone_buffer

    def feed(self, text: str) -> tuple[str, str]:
        self.buffer += text
        visible_parts = []
        thinking_parts = []

        while True:
            open_idx = self.buffer.find(self._OPEN)
            close_idx = self.buffer.find(self._CLOSE)
            if open_idx == -1 and close_idx == -1:
                break

            if open_idx != -1 and (close_idx == -1 or open_idx < close_idx):
                before = self.buffer[:open_idx]
                if not self.resolved:
                    before = self.pending + before  # genuine preamble -> visible
                    self.pending = ""
                    self.resolved = True
                (thinking_parts if self.in_think else visible_parts).append(before)
                self.in_think = True
                self.buffer = self.buffer[open_idx + len(self._OPEN):]
            else:
                # "</think>" always routes the preceding text to reasoning,
                # whether it closes a real opener or is the Qwen3 lone-closer.
                before = self.buffer[:close_idx]
                if not self.resolved:
                    before = self.pending + before  # lone closer -> leaked reasoning
                    self.pending = ""
                    self.resolved = True
                thinking_parts.append(before)
                self.in_think = False
                self.buffer = self.buffer[close_idx + len(self._CLOSE):]

        hold_len = self._partial_marker_len(self.buffer)
        if hold_len > 0:
            resolved_text = self.buffer[:-hold_len]
            self.buffer = self.buffer[-hold_len:]
        else:
            resolved_text = self.buffer
            self.buffer = ""

        if resolved_text:
            if self.resolved:
                # Already know which mode this stream is in -- emit immediately.
                (thinking_parts if self.in_think else visible_parts).append(resolved_text)
            else:
                # Still no marker at all -- a lone "</think>" could still
                # arrive and retroactively make this reasoning. Hold it,
                # unless it's grown past the point we're willing to wait.
                self.pending += resolved_text
                if len(self.pending) > self.max_lone_buffer:
                    visible_parts.append(self.pending)
                    self.pending = ""
                    self.resolved = True

        return "".join(visible_parts), "".join(thinking_parts)

    @classmethod
    def _partial_marker_len(cls, text: str) -> int:
        """Length of the longest tail of `text` that is an unresolved prefix
        of either marker -- held back since the next feed() might complete it."""
        max_len = min(len(text), len(cls._CLOSE))
        for length in range(max_len, 0, -1):
            tail = text[-length:]
            if cls._OPEN.startswith(tail) or cls._CLOSE.startswith(tail):
                return length
        return 0

    def flush(self) -> str:
        """End of stream -- any leftover partial or pending text is ordinary
        text (a model that never used think tags at all)."""
        remaining = self.pending + self.buffer
        self.pending = ""
        self.buffer = ""
        return remaining


def parse_sse_line(line: str) -> Optional[dict]:
    line = line.rstrip("\n")
    if not line:
        return None
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return None
    return json.loads(payload)


def parse_ndjson_line(line: str) -> Optional[dict]:
    s = line.strip()
    if not s:
        return None
    return json.loads(s)


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0), verify=True)


def _prepare(endpoint_name, model, temperature, max_tokens, tools, thinking, messages):
    rec = get_endpoint(endpoint_name)
    if rec is None:
        raise LLMError(404, f"Endpoint '{endpoint_name}' not found")
    provider = rec.provider
    model = model or rec.default_model
    api_key = resolve_api_key(endpoint_name)
    body = build_request(
        provider,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        thinking=thinking,
    )
    url = chat_url(rec.base_url, provider)
    hdrs = headers(provider, api_key)
    return provider, url, hdrs, body


async def call(
    messages: list[dict],
    endpoint_name: str,
    *,
    model: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 0,
    tools: Optional[list] = None,
    thinking: bool = False,
    session_id: Optional[str] = None,  # no-op passthrough for now
    timeout: float = 300,
) -> CallResult:
    provider, url, hdrs, body = _prepare(
        endpoint_name, model, temperature, max_tokens, tools, thinking, messages
    )
    body["stream"] = False

    async with _client(timeout) as client:
        response = await client.post(url, headers=hdrs, json=body)
        if response.status_code >= 400:
            raise LLMError(response.status_code, response.text[:500])
        data = response.json()

    parsed = parse_response(provider, data)
    return CallResult(
        text=parsed["text"],
        reasoning=parsed["reasoning"],
        tool_calls=parsed["tool_calls"],
        usage=parsed["usage"],
        raw=data,
    )


async def stream(
    messages: list[dict],
    endpoint_name: str,
    *,
    model: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 0,
    tools: Optional[list] = None,
    thinking: bool = False,
    session_id: Optional[str] = None,  # no-op passthrough for now
    timeout: float = 300,
) -> AsyncIterator[dict]:
    """Inline <think>...</think> reasoning is filtered out of visible deltas
    via ThinkStreamFilter, which buffers across chunk boundaries. Events
    already tagged thinking (openai reasoning_content, ollama thinking field)
    bypass the filter -- only affects providers with reasoning inline in
    content (Ollama), not OpenAI/Anthropic."""
    provider, url, hdrs, body = _prepare(
        endpoint_name, model, temperature, max_tokens, tools, thinking, messages
    )
    body["stream"] = True
    if provider == "openai":
        body["stream_options"] = {"include_usage": True}

    line_parser = parse_sse_line if provider in ("openai", "anthropic") else parse_ndjson_line
    think_filter = ThinkStreamFilter()

    async with _client(timeout) as client:
        async with client.stream("POST", url, headers=hdrs, json=body) as r:
            if r.status_code >= 400:
                await r.aread()
                raise LLMError(r.status_code, r.text[:500])
            async for line in r.aiter_lines():
                raw = line_parser(line)
                if raw is None:
                    continue
                ev = parse_stream_event(provider, raw)
                if not ev:
                    continue
                if "delta" in ev and not ev.get("thinking"):
                    visible, reasoning = think_filter.feed(ev["delta"])
                    if reasoning:
                        yield {"delta": reasoning, "thinking": True}
                    if visible:
                        yield {"delta": visible}
                else:
                    yield ev

    trailing = think_filter.flush()
    if trailing:
        yield {"delta": trailing}
