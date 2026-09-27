"""Shared SSE envelope for interactive agent HTTP streams.

Same shape as script-writing turns: `event: thinking` / `delta` / `complete`
/ `error`. Failures after the stream has started must be reported inside
the stream (see the `zaolang-editor-drama` skill's script-writing reference
on streaming).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from app.domain.errors import DomainError
from app.llm.client import StreamChunk

SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}


def format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def iter_agent_sse(
    chunks: Iterator[StreamChunk],
    finalize: Callable[[], Any],
    to_complete: Callable[[Any], dict[str, Any]],
    *,
    on_degraded: Callable[[Any], str] | None = None,
) -> Iterator[str]:
    try:
        for chunk in chunks:
            event = "delta" if chunk.kind == "content" else "thinking"
            yield format_sse(event, {"text": chunk.text})
        outcome = finalize()
        if on_degraded and getattr(outcome, "degraded", False):
            yield format_sse("error", {"message": on_degraded(outcome)})
            return
        yield format_sse("complete", to_complete(outcome))
    except DomainError as exc:
        yield format_sse("error", {"message": exc.message})
    except Exception:
        yield format_sse("error", {"message": "服务暂时不可用，请稍后重试。"})
