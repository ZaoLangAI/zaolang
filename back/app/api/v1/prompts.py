"""Prompt-polish for the generation studio.

`ShortformStudio` has its own gated endpoint (`/shortform/prompt/enhance`,
behind the `shortform_studio` feature flag). This one backs
`GenerationStudio`'s "AI 润色" button instead — same shared logic
(`app.domain.prompts`), no feature flag, available to any authenticated user
composing a prompt.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agents import copywriter
from app.api.agent_sse import SSE_HEADERS, format_sse, iter_agent_sse
from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.shortform import PromptDimensionView, PromptEnhanceRequest
from app.api.v1.prompt_enhance import context_from
from app.db import session_scope
from app.domain import prompts
from app.domain.errors import ValidationFailed

router = APIRouter(tags=["prompts"])


@router.post("/generation/prompts/enhance")
def enhance_generation_prompt(
    payload: PromptEnhanceRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> StreamingResponse:
    """把画面描述交给文案 Agent 逐维度诊断并润色，保留用户核心意图。"""
    text = payload.prompt.strip()
    if not text:
        raise ValidationFailed("请先填写画面描述。", fields={"prompt": "不能为空"})

    ctx = context_from(payload)
    chunks, finalize = copywriter.stream_enhance_prompt(
        session,
        prompt=text,
        max_length=prompts.PROMPT_ENHANCE_MAX_LENGTH,
        operation=ctx.operation,
        aspect_ratio=ctx.aspect_ratio,
        duration_seconds=ctx.duration_seconds,
        quality_tier=ctx.quality_tier,
        style_hint=ctx.style_hint,
        has_reference=ctx.has_reference,
        direction=ctx.direction,
        instruction=ctx.instruction,
        asset_kind=ctx.asset_kind,
        user_id=user.id,
    )

    def generate() -> Iterator[str]:
        def _finish() -> prompts.PromptEnhancement:
            with session_scope() as persist:
                outcome = finalize(persist)
                result = prompts.PromptEnhancement(
                    prompt=str(outcome.data["prompt"]),
                    detail_level=str(outcome.data["detail_level"]),
                    feedback=str(outcome.data["feedback"]),
                    dimensions=[
                        prompts.PromptDimension(key=d["key"], status=d["status"], hint=d["hint"])
                        for d in outcome.data.get("dimensions", [])
                    ],
                    additions=list(outcome.data.get("additions", [])),
                    degraded=outcome.degraded,
                )
                persist.commit()
                return result

        yield from iter_agent_sse(
            chunks,
            _finish,
            _enhance_complete_payload,
            on_degraded=lambda _: prompts.ENHANCE_UNAVAILABLE_MESSAGE,
        )

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


def _enhance_complete_payload(result: prompts.PromptEnhancement) -> dict[str, Any]:
    return {
        "prompt": result.prompt,
        "detail_level": result.detail_level,
        "feedback": result.feedback,
        "dimensions": [
            PromptDimensionView(key=d.key, status=d.status, hint=d.hint).model_dump(mode="json")
            for d in result.dimensions
        ],
        "additions": result.additions,
    }


# Re-export so a caller that imported `format_sse` from this module still works.
__all__ = ["router", "format_sse"]
