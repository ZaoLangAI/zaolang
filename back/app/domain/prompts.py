"""Shared prompt-polish logic: one contract, two call sites.

`ShortformStudio`'s "AI 润色" and `GenerationStudio`'s own polish button both
want the same thing — assess how detailed a scene description is, then hand
back a version scaled to that assessment (light touch when it is already
detailed, a fuller rewrite when it is sparse). Both surfaces show the
assessment and let the author accept or ignore it rather than silently
overwriting their text.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed

# 与前端 `PROMPT_MAX_LENGTH`（shortform-studio.tsx / generation-studio.tsx）对齐。
PROMPT_ENHANCE_MAX_LENGTH = 600


@dataclass(slots=True, frozen=True)
class PromptEnhancement:
    prompt: str
    detail_level: str
    feedback: str
    degraded: bool


def enhance(session: Session, *, user_id: str, prompt: str) -> PromptEnhancement:
    """Hands a scene description to the copy agent; returns assessment + polish."""
    text = prompt.strip()
    if not text:
        raise ValidationFailed("请先填写画面描述。", fields={"prompt": "不能为空"})

    from app.agents import copywriter

    outcome = copywriter.enhance_prompt(
        session, prompt=text, max_length=PROMPT_ENHANCE_MAX_LENGTH, user_id=user_id
    )
    return PromptEnhancement(
        prompt=str(outcome.data["prompt"]),
        detail_level=str(outcome.data["detail_level"]),
        feedback=str(outcome.data["feedback"]),
        degraded=outcome.degraded,
    )
