"""The follow-up question shape every agent that asks the author uses.

Three call sites now produce the same structure: the planner's mid-workflow
`clarify` (which suspends a running job), the copy agent's pre-submit
`clarify`, and the scene coach's polish-time questions. The first two were
byte-identical copies of this sanitizer before the third arrived; drift
between them would surface as a question the front end cannot render, since
`QuestionField` (`front/src/components/studio/question-field.tsx`) draws all
three from the same union of kinds.
"""

from __future__ import annotations

from typing import Any

QUESTION_KINDS = ("single_choice", "multi_choice", "free_text")
MAX_QUESTIONS = 4
MAX_OPTIONS = 6

MAX_ID_LEN = 64
MAX_OPTION_LEN = 64
MAX_PROMPT_LEN = 200


def sanitize_questions(raw: Any) -> list[dict[str, Any]]:
    """Keeps only the questions the front end can actually render."""
    if not isinstance(raw, list):
        return []
    sanitized = (sanitize_question(item) for item in raw[:MAX_QUESTIONS])
    return [question for question in sanitized if question is not None]


def sanitize_question(raw: Any) -> dict[str, Any] | None:
    """One question, or `None` when it is unrenderable.

    A choice question without legal options is dropped rather than repaired:
    an empty `OptionGroup` gives the author no way to answer, and a *required*
    question nobody can answer would deadlock the scene studio's submit gate.
    """
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind not in QUESTION_KINDS:
        return None
    question_id = str(raw.get("id") or "").strip()
    question_prompt = str(raw.get("prompt") or "").strip()
    if not question_id or not question_prompt:
        return None

    options: list[dict[str, str]] = []
    if kind in ("single_choice", "multi_choice"):
        raw_options = raw.get("options")
        if isinstance(raw_options, list):
            for option in raw_options[:MAX_OPTIONS]:
                if not isinstance(option, dict):
                    continue
                value = str(option.get("value") or "").strip()
                label = str(option.get("label") or "").strip()
                if value and label:
                    options.append(
                        {"value": value[:MAX_OPTION_LEN], "label": label[:MAX_OPTION_LEN]}
                    )
        if not options:
            return None

    return {
        "id": question_id[:MAX_ID_LEN],
        "kind": kind,
        "prompt": question_prompt[:MAX_PROMPT_LEN],
        "options": options,
        "required": bool(raw.get("required")),
    }
