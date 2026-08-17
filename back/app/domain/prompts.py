"""Shared prompt-polish logic: one contract, two call sites.

`ShortformStudio`'s "AI 润色" and `GenerationStudio`'s own polish button both
want the same thing — diagnose a scene description dimension by dimension,
then hand back a version scaled to that diagnosis (light touch when it is
already detailed, a fuller rewrite when it is sparse). Both surfaces show the
diagnosis and let the author accept, iterate on, or ignore it rather than
silently overwriting their text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed

# 与前端 `PROMPT_MAX_LENGTH`（shortform-studio.tsx / generation-studio.tsx）对齐。
PROMPT_ENHANCE_MAX_LENGTH = 600

# Raised by the callers below when the copy agent degraded. Deliberately not a
# silent fallback: the degraded path echoes the author's own text back, and
# presenting that as a polish is what made the feature look broken.
ENHANCE_UNAVAILABLE_MESSAGE = "AI 润色暂时不可用，请稍后重试。"


@dataclass(slots=True, frozen=True)
class PromptContext:
    """What the studio already knows about the job being composed.

    Every field is optional because both studios grew their own controls at
    different times, and a caller that cannot supply one must still be able
    to ask for a polish.
    """

    operation: str = ""
    aspect_ratio: str = ""
    duration_seconds: int | None = None
    quality_tier: str = ""
    style_hint: str = ""
    has_reference: bool = False
    # This round's requested adjustment, when the author is iterating on a
    # suggestion rather than asking for the first one.
    direction: str = ""
    instruction: str = ""
    # The image job's `ImageAssetKind` (`character`/`scene`/`cover`/`general`),
    # empty for a video/audio polish or a caller that has not picked one yet.
    # Routes to that kind's dedicated default agent — see
    # `app.agents.copywriter.enhance_prompt`.
    asset_kind: str = ""


@dataclass(slots=True, frozen=True)
class PromptDimension:
    key: str
    status: str
    hint: str


@dataclass(slots=True, frozen=True)
class PromptEnhancement:
    prompt: str
    detail_level: str
    feedback: str
    dimensions: list[PromptDimension] = field(default_factory=list)
    additions: list[str] = field(default_factory=list)
    # Not part of the API response: callers turn this into an error rather
    # than showing the fallback text. Kept on the result instead of raised
    # here so the endpoint can commit the `AgentRun` first — `get_db` drops
    # the transaction on the way out, and a degradation nobody recorded is
    # one nobody can debug.
    degraded: bool = False


def enhance(
    session: Session,
    *,
    user_id: str,
    prompt: str,
    context: PromptContext | None = None,
) -> PromptEnhancement:
    """Hands a scene description to the copy agent; returns diagnosis + polish."""
    text = prompt.strip()
    if not text:
        raise ValidationFailed("请先填写画面描述。", fields={"prompt": "不能为空"})

    from app.agents import copywriter

    ctx = context or PromptContext()
    outcome = copywriter.enhance_prompt(
        session,
        prompt=text,
        max_length=PROMPT_ENHANCE_MAX_LENGTH,
        operation=ctx.operation,
        aspect_ratio=ctx.aspect_ratio,
        duration_seconds=ctx.duration_seconds,
        quality_tier=ctx.quality_tier,
        style_hint=ctx.style_hint,
        has_reference=ctx.has_reference,
        direction=ctx.direction,
        instruction=ctx.instruction,
        asset_kind=ctx.asset_kind,
        user_id=user_id,
    )
    return PromptEnhancement(
        prompt=str(outcome.data["prompt"]),
        detail_level=str(outcome.data["detail_level"]),
        feedback=str(outcome.data["feedback"]),
        dimensions=[
            PromptDimension(key=d["key"], status=d["status"], hint=d["hint"])
            for d in outcome.data.get("dimensions", [])
        ],
        additions=list(outcome.data.get("additions", [])),
        degraded=outcome.degraded,
    )
