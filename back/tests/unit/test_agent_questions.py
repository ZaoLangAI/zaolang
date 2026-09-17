"""The follow-up question shape shared by every agent that asks the author."""

from __future__ import annotations

from app.agents import copywriter, planner
from app.agents import questions as agent_questions


def test_the_clarify_slots_share_one_shape() -> None:
    """Two byte-identical sanitizers used to live here; a third arrived with
    the scene coach's polish-time questions."""
    assert planner.QUESTION_KINDS is agent_questions.QUESTION_KINDS
    assert copywriter.QUESTION_KINDS is agent_questions.QUESTION_KINDS
    assert planner.MAX_CLARIFY_QUESTIONS == agent_questions.MAX_QUESTIONS
    assert copywriter.MAX_ENHANCE_OPTIONS == agent_questions.MAX_OPTIONS


def test_a_choice_question_without_options_is_dropped() -> None:
    """An empty `OptionGroup` gives the author no way to answer, and a
    *required* one would deadlock the scene studio's submit gate."""
    assert (
        agent_questions.sanitize_questions(
            [
                {
                    "id": "q",
                    "kind": "single_choice",
                    "prompt": "哪个？",
                    "options": [],
                    "required": True,
                }
            ]
        )
        == []
    )


def test_free_text_needs_no_options() -> None:
    [question] = agent_questions.sanitize_questions(
        [{"id": "q", "kind": "free_text", "prompt": "补充说明", "required": False}]
    )
    assert question == {
        "id": "q",
        "kind": "free_text",
        "prompt": "补充说明",
        "options": [],
        "required": False,
    }


def test_unknown_kinds_and_junk_are_dropped() -> None:
    assert agent_questions.sanitize_questions("not a list") == []
    assert agent_questions.sanitize_questions([None, 3, {"id": "", "kind": "free_text"}]) == []
    assert (
        agent_questions.sanitize_questions([{"id": "q", "kind": "slider", "prompt": "多少"}]) == []
    )


def test_questions_and_options_are_capped() -> None:
    raw = [
        {
            "id": f"q{i}",
            "kind": "single_choice",
            "prompt": "选一个",
            "options": [{"value": f"v{j}", "label": f"l{j}"} for j in range(10)],
        }
        for i in range(10)
    ]
    sanitized = agent_questions.sanitize_questions(raw)
    assert len(sanitized) == agent_questions.MAX_QUESTIONS
    assert all(len(q["options"]) == agent_questions.MAX_OPTIONS for q in sanitized)
