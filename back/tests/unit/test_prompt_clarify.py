"""`app.domain.shortform.clarify.clarify`: pre-submission clarifying
questions, shortform-only (not shared with the generation studio)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.agents.base import AgentOutcome
from app.domain.errors import ValidationFailed
from app.domain.shortform import clarify
from app.models import User


def test_a_sparse_description_gets_a_structured_question(db: Session, author: User) -> None:
    result = clarify.clarify(db, user_id=author.id, prompt="女孩在海边")

    assert result.needs_clarification is True
    assert result.questions
    question = result.questions[0]
    assert question.kind in ("single_choice", "multi_choice", "free_text")
    assert question.prompt
    if question.kind != "free_text":
        assert len(question.options) >= 2
    assert result.degraded is False


def test_a_detailed_description_needs_no_clarification(db: Session, author: User) -> None:
    text = (
        "黄昏时分，一位穿着白色长裙的女孩独自站在海边礁石上，海风吹动她的裙摆，"
        "镜头缓慢从远景推近到她的侧脸特写，逆光剪影，暖橙色调，长焦压缩景深"
    )
    result = clarify.clarify(db, user_id=author.id, prompt=text)

    assert result.needs_clarification is False
    assert result.questions == []


def test_blank_input_is_rejected_before_calling_the_agent(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        clarify.clarify(db, user_id=author.id, prompt="   ")


def test_a_degraded_model_call_never_blocks_submission(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback must be safe-by-default: a gateway hiccup should never
    force a dead end on the author."""

    def _degraded(*args, **kwargs):  # type: ignore[no-untyped-def]
        return AgentOutcome(
            data=dict(copywriter.CLARIFY_FALLBACK),
            raw_text="",
            degraded=True,
            model="stub:test",
            agent_run_id="agent-run-test",
        )

    monkeypatch.setattr(copywriter, "run_agent", _degraded)

    result = clarify.clarify(db, user_id=author.id, prompt="女孩在海边")

    assert result.needs_clarification is False
    assert result.questions == []
    assert result.degraded is True


def test_questions_are_capped_and_malformed_ones_dropped(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six candidate questions, one malformed (missing prompt) and one
    choice question with no options — the cap and the option requirement
    both come from `copywriter.clarify`'s own sanitisation, not the model."""
    raw_questions = [
        {"id": f"q{i}", "kind": "free_text", "prompt": f"问题{i}", "options": [], "required": False}
        for i in range(6)
    ]
    raw_questions[1] = {"id": "bad", "kind": "free_text", "prompt": "", "options": []}
    raw_questions[2] = {"id": "no-options", "kind": "single_choice", "prompt": "选哪个？"}

    def _fake(*args, **kwargs):  # type: ignore[no-untyped-def]
        return AgentOutcome(
            data={"needs_clarification": True, "questions": raw_questions},
            raw_text="",
            degraded=False,
            model="stub:test",
            agent_run_id="agent-run-test",
        )

    monkeypatch.setattr(copywriter, "run_agent", _fake)

    result = clarify.clarify(db, user_id=author.id, prompt="女孩在海边")

    assert len(result.questions) <= copywriter.MAX_CLARIFY_QUESTIONS
    assert all(q.prompt for q in result.questions)
    assert all(q.kind != "single_choice" or q.options for q in result.questions)
