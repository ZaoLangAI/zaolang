"""Prompt-polish for the creation studios.

`POST /generation/prompts/enhance` is the only polish route: it backs the
"AI 润色" button of every studio prompt field (`prompt-field.tsx`), has no
feature flag, and is open to any authenticated user composing a prompt. It
streams SSE — a `matched` frame, then the shared `iter_agent_sse` frames —
over the logic in `app.domain.prompts`.
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
from app.api.v1.prompt_enhance import context_from, question_views
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
    # Runs before the stream is opened, on the request session, because it is
    # itself an LLM call and must not compete with the polish stream for the
    # connection. The panel learns what it matched from the `matched` frame
    # below rather than from a "matching now" one: no byte of this response
    # can be sent until this returns, so an in-progress notice would arrive
    # after the work it announces.
    reference_skills = prompts.matched_reference_skills(
        session, prompt=text, operation=ctx.operation, user_id=user.id
    )
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
        script_segment=ctx.script_segment,
        question_answers=ctx.question_answers,
        reference_skills=reference_skills,
        user_id=user.id,
    )

    def generate() -> Iterator[str]:
        if reference_skills:
            yield format_sse(
                "matched",
                {
                    "referenced_skills": [
                        {"id": entry["id"], "title": entry["title"]}
                        for entry in reference_skills
                    ]
                },
            )

        def _finish() -> prompts.PromptEnhancement:
            with session_scope() as persist:
                outcome = finalize(persist)
                segment = outcome.data.get("script_segment")
                result = prompts.PromptEnhancement(
                    prompt=str(outcome.data["prompt"]),
                    detail_level=str(outcome.data["detail_level"]),
                    feedback=str(outcome.data["feedback"]),
                    dimensions=[
                        prompts.PromptDimension(key=d["key"], status=d["status"], hint=d["hint"])
                        for d in outcome.data.get("dimensions", [])
                    ],
                    additions=list(outcome.data.get("additions", [])),
                    applied_format_skills=prompts.applied_format_skills_from(
                        outcome.data.get("applied_format_skills")
                    ),
                    referenced_skills=prompts.referenced_skills_from(
                        outcome.data.get("referenced_skills")
                    ),
                    questions=prompts.questions_from(outcome.data.get("questions")),
                    degraded=outcome.degraded,
                    script_segment=segment if isinstance(segment, dict) else None,
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
    payload: dict[str, Any] = {
        "prompt": result.prompt,
        "detail_level": result.detail_level,
        "feedback": result.feedback,
        "dimensions": [
            PromptDimensionView(key=d.key, status=d.status, hint=d.hint).model_dump(mode="json")
            for d in result.dimensions
        ],
        "additions": result.additions,
        "applied_format_skills": [
            {"id": skill.id, "title": skill.title} for skill in result.applied_format_skills
        ],
        "referenced_skills": [
            {"id": skill.id, "title": skill.title} for skill in result.referenced_skills
        ],
        "questions": [
            view.model_dump(mode="json") for view in question_views(result.questions)
        ],
    }
    if result.script_segment is not None:
        payload["script_segment"] = result.script_segment
    return payload


# Re-export so a caller that imported `format_sse` from this module still works.
__all__ = ["format_sse", "router"]
