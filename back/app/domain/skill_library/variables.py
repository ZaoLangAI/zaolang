"""A creation workflow's variable form.

A workflow is an ordinary `CreationSkill` whose `params_json` carries a
`variables` list. That list uses the *same* field model the agents use for
follow-up questions (`app.agents.questions`), rather than a second schema:
`front/src/components/studio/question-field.tsx` already renders that union of
kinds, so a workflow form costs no new renderer and cannot drift from one.

This lives in `skill_library` and not in the canvas package even though the
canvas is the only thing that runs a workflow today: "does this skill declare
a form?" is a fact about the skill, and `GET /v1/skills` has to answer it.
Putting it beside the runner would make the generic skills API import the
canvas.
"""

from __future__ import annotations

from typing import Any

from app.agents.questions import sanitize_questions
from app.models import CreationSkill

VARIABLES_KEY = "variables"


def variables_of(skill: CreationSkill) -> list[dict[str, Any]]:
    """The workflow's questions, sanitised.

    Read through `sanitize_questions` rather than trusted: `params_json` is an
    unvalidated bag, so a skill written before this feature existed — or by a
    client that put something else under the key — degrades to "not a
    workflow" instead of reaching the renderer as a malformed form.
    """
    params = skill.params_json or {}
    return sanitize_questions(params.get(VARIABLES_KEY))


def has_variables(skill: CreationSkill) -> bool:
    return bool(variables_of(skill))


__all__ = ["VARIABLES_KEY", "has_variables", "variables_of"]
