"""Response normalisation for the OpenAI-compatible gateway.

The three models behind the gateway behave differently, and every difference
observed against the live endpoint is handled here rather than in each agent:

* `ling-3.0-flash-free` is a reasoning model. Thinking tokens are billed against
  `max_tokens`, so a small budget returns empty `content` with
  `finish_reason=length` and the text only present in `reasoning_details`.
* Thinking models emit `<think>...</think>` before the payload even when
  `response_format={"type": "json_object"}` is requested.
* `doubao-seed-2-1-pro` returns clean JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
UNCLOSED_THINK = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)
FENCED_JSON = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


@dataclass(slots=True)
class NormalizedResponse:
    text: str
    data: dict[str, Any] | None = None
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    # Set when content had to be recovered from a reasoning-only response.
    recovered_from_reasoning: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


def strip_thinking(text: str) -> str:
    """Removes think blocks, including one left unterminated by truncation."""
    cleaned = THINK_BLOCK.sub("", text)
    cleaned = UNCLOSED_THINK.sub("", cleaned)
    return cleaned.strip()


def extract_json(text: str) -> dict[str, Any] | None:
    """Finds a JSON object inside free-form model output.

    Tries the whole string, then a fenced block, then the outermost balanced
    braces. Returns None rather than raising so the caller can decide between
    a repair round-trip and a fallback.
    """
    candidate = text.strip()
    if not candidate:
        return None

    parsed = _try_load(candidate)
    if parsed is not None:
        return parsed

    fenced = FENCED_JSON.search(candidate)
    if fenced:
        parsed = _try_load(fenced.group(1))
        if parsed is not None:
            return parsed

    span = _outermost_object(candidate)
    if span is not None:
        return _try_load(span)
    return None


def _try_load(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _outermost_object(text: str) -> str | None:
    """Scans for a balanced `{...}`, ignoring braces inside string literals."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def normalize_completion(raw: Any, *, expect_json: bool) -> NormalizedResponse:
    """Turns a chat completion into a predictable shape.

    Accepts either an OpenAI SDK object or a plain dict, so tests can feed
    recorded payloads without constructing SDK types.
    """
    payload = raw if isinstance(raw, dict) else _to_dict(raw)
    choices = payload.get("choices") or [{}]
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    finish_reason = str(choice.get("finish_reason") or "stop")

    content = (message.get("content") or "").strip()
    warnings: list[str] = []
    recovered = False

    if not content:
        # Reasoning-only response: the answer exists but never made it into
        # `content` because the budget ran out during thinking.
        reasoning = _reasoning_text(message)
        if reasoning:
            content = reasoning
            recovered = True
            warnings.append("content_recovered_from_reasoning")

    text = strip_thinking(content)
    data = extract_json(text) if expect_json else None
    if expect_json and data is None and text:
        warnings.append("json_parse_failed")
    if finish_reason == "length":
        warnings.append("truncated_by_max_tokens")

    usage = payload.get("usage") or {}
    return NormalizedResponse(
        text=text,
        data=data,
        finish_reason=finish_reason,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        model=str(payload.get("model") or ""),
        recovered_from_reasoning=recovered,
        warnings=warnings,
    )


def _reasoning_text(message: dict[str, Any]) -> str:
    """Collects reasoning text across the shapes the gateway returns."""
    direct = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    details = message.get("reasoning_details")
    if isinstance(details, list):
        parts = [
            str(item.get("text", "")).strip()
            for item in details
            if isinstance(item, dict) and item.get("text")
        ]
        joined = "\n".join(part for part in parts if part)
        if joined:
            return joined
    return ""


def _to_dict(obj: Any) -> dict[str, Any]:
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                value = method()
            except TypeError:
                continue
            if isinstance(value, dict):
                return value
    return {}
