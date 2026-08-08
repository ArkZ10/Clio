"""Pure request/response transformation logic. No HTTP, no network -- keeps
the openai/ollama/anthropic wire-format differences testable with canned
dicts, no live endpoint required. client.py's call()/stream() wrap these.
"""
import re
from typing import Any, Optional

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_LONE_CLOSE_THINK_RE = re.compile(r"\A(.*?)</think>\s*", re.DOTALL)


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """Strips reasoning_content/thinking keys before sending upstream --
    DeepSeek 400s on echoed reasoning, and it degrades quality generally.
    Returns a new list, doesn't mutate the input."""
    cleaned = []
    for m in messages:
        c = dict(m)
        c.pop("reasoning_content", None)
        c.pop("thinking", None)
        cleaned.append(c)
    return cleaned


def strip_think(text: str) -> tuple[str, str]:
    """Removes <think>...</think> spans. Returns (clean_text, reasoning) --
    the concatenated removed spans, in order. Also handles a lone leading
    "</think>" with no opener (some templates pre-seed it in the prompt) --
    everything before that closing tag is reasoning too."""
    if not text:
        return text or "", ""

    reasoning_parts = _THINK_RE.findall(text)
    clean = _THINK_RE.sub("", text)

    lone = _LONE_CLOSE_THINK_RE.match(clean)
    if lone:
        reasoning_parts.append(lone.group(1))
        clean = clean[lone.end():]

    return clean, "".join(reasoning_parts)


def build_request(
    provider: str,
    *,
    messages: list[dict],
    model: str,
    temperature: float = 1.0,
    max_tokens: int = 0,
    tools: Optional[list] = None,
    thinking: bool = False,
) -> dict:
    messages = sanitize_messages(messages)

    if provider == "openai":
        body: dict[str, Any] = {"model": model, "messages": messages}
        if thinking:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = "medium"
        else:
            body["temperature"] = temperature
        if max_tokens > 0:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        return body

    if provider == "ollama":
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens > 0:
            options["num_predict"] = max_tokens
        body = {
            "model": model,
            "messages": messages,
            "options": options,
            "think": bool(thinking),
        }
        if tools:
            body["tools"] = tools
        return body

    if provider == "anthropic":
        system: Optional[str] = None
        remaining = []
        for m in messages:
            if m.get("role") == "system" and system is None:
                system = m.get("content")
            else:
                remaining.append(m)

        body = {
            "model": model,
            "messages": remaining,
            "max_tokens": max_tokens if max_tokens > 0 else 4096,
            "temperature": temperature,
        }
        if system is not None:
            body["system"] = system
        if tools:
            body["tools"] = tools
        if thinking:
            body["thinking"] = {"type": "enabled", "budget_tokens": 2048}
        return body

    raise ValueError(f"Unknown provider: {provider}")


def parse_response(provider: str, data: dict) -> dict:
    if provider == "openai":
        msg = data["choices"][0]["message"]
        return {
            "text": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "usage": data.get("usage") or {},
        }

    if provider == "ollama":
        msg = data["message"]
        reasoning = msg.get("thinking") or ""
        text = msg.get("content") or ""
        text, extra_reasoning = strip_think(text)
        if extra_reasoning:
            reasoning = (reasoning + extra_reasoning) if reasoning else extra_reasoning
        usage = {}
        if "eval_count" in data or "prompt_eval_count" in data:
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            }
        return {
            "text": text,
            "reasoning": reasoning,
            "tool_calls": msg.get("tool_calls") or [],
            "usage": usage,
        }

    if provider == "anthropic":
        text_parts = []
        reasoning_parts = []
        tool_calls = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "thinking":
                reasoning_parts.append(block.get("thinking") or "")
            elif btype == "tool_use":
                tool_calls.append(block)
        return {
            "text": "".join(text_parts),
            "reasoning": "".join(reasoning_parts),
            "tool_calls": tool_calls,
            "usage": data.get("usage") or {},
        }

    raise ValueError(f"Unknown provider: {provider}")


def parse_stream_event(provider: str, chunk: dict) -> Optional[dict]:
    if provider == "openai":
        choices = chunk.get("choices") or []
        if choices:
            d = choices[0].get("delta") or {}
            if d.get("reasoning_content"):
                return {"delta": d["reasoning_content"], "thinking": True}
            if d.get("content"):
                return {"delta": d["content"]}
            if d.get("tool_calls"):
                return {"tool_calls": d["tool_calls"]}
        if chunk.get("usage"):
            return {"usage": chunk["usage"]}
        return None

    if provider == "ollama":
        m = chunk.get("message") or {}
        if m.get("thinking"):
            return {"delta": m["thinking"], "thinking": True}
        if m.get("content"):
            return {"delta": m["content"]}
        if chunk.get("done") is True:
            return {
                "usage": {
                    "prompt_tokens": chunk.get("prompt_eval_count", 0),
                    "completion_tokens": chunk.get("eval_count", 0),
                }
            }
        return None

    if provider == "anthropic":
        ctype = chunk.get("type")
        if ctype == "content_block_delta":
            delta = chunk.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                return {"delta": delta.get("text") or ""}
            if dtype == "thinking_delta":
                return {"delta": delta.get("thinking") or "", "thinking": True}
            return None
        if ctype == "message_delta":
            usage = chunk.get("usage")
            if usage:
                return {"usage": usage}
        return None

    raise ValueError(f"Unknown provider: {provider}")
