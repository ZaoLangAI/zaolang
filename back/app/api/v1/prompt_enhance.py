"""Request/response plumbing for the prompt-polish route (`api/v1/prompts.py`)."""

from __future__ import annotations

from app.api.schemas.shortform import PromptEnhanceRequest, PromptQuestionView
from app.domain import prompts


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
        asset_presets=_asset_presets(payload),
    )


def _asset_presets(payload: PromptEnhanceRequest) -> dict | None:
    presets: dict[str, object] = {}
    if payload.character_expressions:
        presets["character_expressions"] = list(payload.character_expressions)
    for field in ("scene_lighting", "scene_weather", "scene_state", "scene_period"):
        value = getattr(payload, field)
        if value:
            presets[field] = value
    return presets or None


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
