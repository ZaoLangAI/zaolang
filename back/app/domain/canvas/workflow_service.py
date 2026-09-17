"""Creation workflows: a `CreationSkill` with a variable form in front of it.

A workflow is not a new object. It is an ordinary `CreationSkill` whose
`params_json` carries a `variables` list — the same field model the agents use
for follow-up questions (`app.agents.questions`), so the front end renders it
with the `QuestionField` component it already has. Running one produces a
`CanvasAgentRun` with `origin = workflow`, which means landing, cancelling,
the workbench and the change stream are the mechanisms built for the Agent
rather than a second set that would drift from them.

Two boundaries this module exists to hold:

* **Variables never reach the provider.** They are questions, answered here,
  and only the *answers* are substituted into the prompt.
  `folding.RESERVED_TEMPLATE_KEYS` keeps `execute_skill_context` from folding
  the question list itself into `ctx.params`; this module keeps it out of the
  request it builds.
* **`GenerationParams` gains nothing.** A variable belongs to one run, not to
  the skill and not to the platform's generation contract. Substituting in the
  domain layer costs one shared helper (`skill_library.folding`); adding a
  field to the global schema for one canvas feature would be the wrong layer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.questions import MAX_OPTIONS, MAX_QUESTIONS
from app.domain.canvas import graph_service
from app.domain.canvas import service as canvas_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.skill_library import service as skill_library_service
from app.domain.skill_library.folding import fold_params_prompt, foldable_params
from app.domain.skill_library.variables import has_variables, variables_of
from app.models import CanvasAgentRun, CanvasAgentTask, CanvasNode, CreationSkill
from app.models.base import utcnow
from app.models.enums import (
    CanvasAgentRunOrigin,
    CanvasAgentRunStatus,
    Operation,
    QualityTier,
)

# Where a workflow's result lands relative to the card it was started from.
# Same geometry as the Agent's, so a canvas does not develop two conventions
# for "output appears to the right".
DROP_OFFSET_X = graph_service.DEFAULT_RESULT_WIDTH + 120
DROP_SPACING_Y = 220

MAX_ANSWER_LEN = 200

_VIDEO_OPERATIONS = frozenset({Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO})
DEFAULT_VIDEO_SECONDS = 5


def _answer_text(question: dict[str, Any], raw: Any) -> str:
    """One answer as the string that will be substituted into the prompt."""
    kind = question["kind"]
    if kind == "multi_choice":
        values = raw if isinstance(raw, list) else []
        legal = {option["value"] for option in question["options"]}
        chosen = [str(value) for value in values[:MAX_OPTIONS] if str(value) in legal]
        return "、".join(chosen)
    if kind == "single_choice":
        legal = {option["value"] for option in question["options"]}
        value = str(raw or "")
        # An illegal option is dropped, not passed through: the option list is
        # the author's vocabulary, and a client-supplied value outside it would
        # let anyone write arbitrary text into a "choice".
        return value if value in legal else ""
    return str(raw or "").strip()[:MAX_ANSWER_LEN]


def resolve_answers(
    skill: CreationSkill, answers: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Validate the submitted answers against the workflow's own questions.

    Returns the questions and the cleaned answers keyed by question id. A
    required question with no usable answer is an error rather than an empty
    substitution — silently generating without it would spend credits on
    something the author said was mandatory.
    """
    questions = variables_of(skill)
    if not questions:
        raise ValidationFailed("这条技能不是创作工作流。")
    if len(questions) > MAX_QUESTIONS:  # pragma: no cover - sanitiser already caps this
        questions = questions[:MAX_QUESTIONS]

    supplied = answers or {}
    resolved: dict[str, str] = {}
    for question in questions:
        text = _answer_text(question, supplied.get(question["id"]))
        if not text and question["required"]:
            raise ValidationFailed(f"请先回答：{question['prompt']}")
        if text:
            resolved[question["id"]] = text
    return questions, resolved


def compose_prompt(
    skill: CreationSkill, questions: list[dict[str, Any]], answers: dict[str, str]
) -> str:
    """The recipe's prompt with the answers folded in.

    Substitution is by appending "问题：答案", not by templating `{id}` into the
    prompt text. A placeholder syntax would make every workflow's prompt a
    small language with its own escaping and failure modes; naming the question
    beside its answer reads correctly to a model and cannot break the recipe
    when an author renames a variable.
    """
    fold = foldable_params(skill.params_json)
    prompt = fold_params_prompt("", fold)
    parts = [prompt] if prompt else []
    by_id = {question["id"]: question for question in questions}
    for question_id, value in answers.items():
        label = by_id[question_id]["prompt"]
        parts.append(f"{label}：{value}")
    return "，".join(parts)


def _operation_for(skill: CreationSkill) -> str:
    """The operation a workflow run submits.

    Taken from the skill's own `applicable_operations_json` rather than from
    the request: the recipe was written for a particular modality, and letting
    a caller pick would produce a video job carrying a still-frame recipe. The
    first declared operation is the primary one; a skill that declares none is
    not runnable as a workflow, because nothing says what to submit.
    """
    declared = skill.applicable_operations_json or []
    for candidate in declared:
        try:
            return Operation(candidate).value
        except ValueError:
            continue
    raise ValidationFailed("这条技能没有声明适用的生成类型，无法作为工作流运行。")


def start_run(
    session: Session,
    *,
    user_id: str,
    canvas_id: str,
    skill_id: str,
    node_id: str,
    answers: dict[str, Any] | None,
    quality_tier: str = QualityTier.STANDARD.value,
    max_credits: int | None = None,
) -> CanvasAgentRun:
    """Build a priced, unconfirmed run from a workflow skill.

    Stops at `awaiting_confirm` exactly like a planned run: the variable form
    *is* the step before confirmation, the quote is shown on it, and
    `agent_service.confirm_run` is what spends anything. Nothing here charges.
    """
    project = canvas_service.get_project(session, user_id=user_id, canvas_id=canvas_id)
    node = session.get(CanvasNode, node_id)
    if node is None or node.canvas_id != project.id:
        raise NotFound("画布节点不存在。")

    # Visibility first, then entitlement — the same two-step the studio uses.
    # A locked paid skill can sit on the canvas as a card (see
    # `canvas_service._bound_skills`); running it is where unlocking bites.
    skill = skill_library_service.get_usable(session, skill_id=skill_id, viewer_id=user_id)
    skill_library_service.assert_unlocked_for_use(session, skill, user_id)

    # Checked before a credit moves, for the same reason the Agent path checks
    # it: a job that succeeds but has nowhere to land is money spent for
    # nothing.
    if graph_service.node_count(session, project.id) >= graph_service.MAX_NODES:
        raise ValidationFailed("画布节点已接近上限，请先清理后再运行工作流。")

    questions, resolved = resolve_answers(skill, answers)
    operation = _operation_for(skill)
    prompt = compose_prompt(skill, questions, resolved)
    if not prompt:
        raise ValidationFailed("这条工作流没有生成任何提示词。")

    params: dict[str, Any] = {"prompt": prompt}
    aspect = (skill.params_json or {}).get("aspect_ratio")
    if isinstance(aspect, str) and aspect:
        params["aspect_ratio"] = aspect
    if Operation(operation) in _VIDEO_OPERATIONS:
        params["duration_seconds"] = DEFAULT_VIDEO_SECONDS
    # The skill rides along as context so `execute_skill_context` folds the
    # rest of the recipe server-side — the same path a studio submission takes.
    # `variables` is excluded there by `RESERVED_TEMPLATE_KEYS`.
    params["skill_ids"] = [skill.id]

    run = CanvasAgentRun(
        canvas_id=project.id,
        user_id=user_id,
        origin=CanvasAgentRunOrigin.WORKFLOW.value,
        goal=skill.title,
        agent_node_id=node.id,
        context_node_ids_json=[node.id],
        context_digest_json={"skill_id": skill.id, "answers": resolved},
        plan_json={"summary": skill.title, "variables": questions, "answers": resolved},
        max_credits=max_credits,
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()

    quote = jobs_service.quote_for(
        session,
        operation=operation,
        quality_tier=quality_tier,
        duration_seconds=int(params.get("duration_seconds") or 0),
    )
    session.add(
        CanvasAgentTask(
            run_id=run.id,
            ordinal=0,
            operation=operation,
            quality_tier=quality_tier,
            request_json=params,
            drop_x=node.position_x + DROP_OFFSET_X,
            drop_y=node.position_y,
        )
    )
    run.quoted_credits = quote.credits
    run.status = CanvasAgentRunStatus.AWAITING_CONFIRM.value
    session.flush()
    return run


__all__ = [
    "compose_prompt",
    "has_variables",
    "resolve_answers",
    "start_run",
    "variables_of",
]
