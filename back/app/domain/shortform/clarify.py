"""Pre-submission clarifying questions for the shortform studio.

Kept separate from `app.domain.prompts` on purpose: that module's docstring
declares it shared with `GenerationStudio`'s own polish button, and this
capability is shortform-only. A shared home would risk a future maintainer
wiring clarification into the general studio without meaning to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed

CLARIFY_PROMPT_MAX_LENGTH = 600

QuestionKind = Literal["single_choice", "multi_choice", "free_text"]


@dataclass(slots=True, frozen=True)
class ClarifyOption:
    value: str
    label: str


@dataclass(slots=True, frozen=True)
class ClarifyQuestion:
    id: str
    kind: QuestionKind
    prompt: str
    options: list[ClarifyOption] = field(default_factory=list)
    required: bool = False


@dataclass(slots=True, frozen=True)
class ClarifyResult:
    needs_clarification: bool
    questions: list[ClarifyQuestion]
    degraded: bool


def clarify(session: Session, *, user_id: str, prompt: str) -> ClarifyResult:
    """Hands a scene description to the copy agent's clarify slot."""
    text = prompt.strip()
    if not text:
        raise ValidationFailed("请先填写画面描述。", fields={"prompt": "不能为空"})

    from app.agents import copywriter

    outcome = copywriter.clarify(session, prompt=text, user_id=user_id)
    questions = [
        ClarifyQuestion(
            id=str(q["id"]),
            kind=q["kind"],
            prompt=str(q["prompt"]),
            options=[ClarifyOption(**o) for o in q["options"]],
            required=bool(q["required"]),
        )
        for q in outcome.data["questions"]
    ]
    return ClarifyResult(
        needs_clarification=bool(outcome.data["needs_clarification"]),
        questions=questions,
        degraded=outcome.degraded,
    )
