"""Request/response plumbing for the prompt-polish route (`api/v1/prompts.py`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.shortform import (
    AppliedFormatSkillView,
    PromptDimensionView,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
    PromptQuestionView,
    ReferencedSkillView,
)
from app.domain import prompts
from app.domain.errors import ProviderTemporaryFailure


def context_from(payload: PromptEnhanceRequest) -> prompts.PromptContext:
    # `PromptContext.asset_kind` is a bare string that can carry either axis's
    # value — `video_asset_kind` wins when present, since a video job's
    # `asset_kind` is never meaningfully set (see the field's own docstring).
    resolved_asset_kind = payload.video_asset_kind or payload.asset_kind or ""
    segment = payload.script_segment.model_dump(mode="json") if payload.script_segment else None
    return prompts.PromptContext(
        operation=payload.operation or "",
        aspect_ratio=payload.aspect_ratio or "",
        duration_seconds=payload.duration_seconds,
        quality_tier=payload.quality_tier or "",
        style_hint=payload.style_hint,
        has_reference=payload.has_reference,
        direction=payload.direction or "",
        instruction=payload.instruction,
        asset_kind=resolved_asset_kind,
        script_segment=segment,
        question_answers=dict(payload.question_answers) or None,
    )


def enhanced_response(session: Session, result: prompts.PromptEnhancement) -> PromptEnhanceResponse:
    """Commits the `AgentRun`, then fails loudly if the agent degraded.

    The order matters both ways. Committing first keeps the degraded call in
    the ops console — `get_db` never commits on the way out, so raising before
    this would erase the only record that the gateway was unreachable. Raising
    after it is what stops the caller from presenting the fallback (which is
    the author's own text, echoed back) as a polish: an honest 503 is more
    useful than a suggestion that suggests nothing.
    """
    session.commit()
    if result.degraded:
        raise ProviderTemporaryFailure(prompts.ENHANCE_UNAVAILABLE_MESSAGE)
    return PromptEnhanceResponse(
        prompt=result.prompt,
        detail_level=result.detail_level,
        feedback=result.feedback,
        dimensions=[
            PromptDimensionView(key=d.key, status=d.status, hint=d.hint) for d in result.dimensions
        ],
        additions=result.additions,
        applied_format_skills=[
            AppliedFormatSkillView(id=skill.id, title=skill.title)
            for skill in result.applied_format_skills
        ],
        referenced_skills=[
            ReferencedSkillView(id=skill.id, title=skill.title)
            for skill in result.referenced_skills
        ],
        questions=question_views(result.questions),
        script_segment=result.script_segment,
    )


def question_views(questions: list[prompts.PromptQuestion]) -> list[PromptQuestionView]:
    """The questions as the SSE `complete` frame publishes them."""
    return [
        PromptQuestionView(
            id=question.id,
            kind=question.kind,
            prompt=question.prompt,
            options=[{"value": o["value"], "label": o["label"]} for o in question.options],
            required=question.required,
        )
        for question in questions
    ]
