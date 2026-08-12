"""Planner agent: turns an intent into an executable generation plan."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.agents.slots import DEFAULT_SLOT
from app.models.enums import AgentName, Operation, QualityTier

SYSTEM_PROMPT = f"""你是造浪平台的创作规划器。根据用户意图与来源作品参数，产出一个可执行的生成计划。
规则：
- operation 只能是 text_to_image / text_to_video / image_to_video / video_to_video
- 若用户没有明确要求高质量，优先推荐 standard 档位以控制成本
- prompt_enhancements 是对原始描述的补充，不要改变用户的核心意图
- operation 为视频类时，prompt_enhancements 优先补充镜头/运镜、节奏与时长，不要只写氛围形容词
- negative_prompt_suggestions 是生成时需要规避的反面描述，用于降低常见失败率
  （例如复杂动作场景里的肢体/面部畸变、镜头抖动伪影），与本次意图无关时留空数组
- 涉及暴力、伤害等敏感画面时，prompt_enhancements 只补充镜头语言与氛围
  不要新增用户描述中没有出现的血腥、伤害细节——那类内容交给安全审核环节单独处理
- 不要编造用户没有提供的素材

{JSON_INSTRUCTION}
格式：{{"operation": string, "steps": [{{"name": string, "detail": string}}],
"recommended_tier": "preview"|"standard"|"cinematic", "prompt_enhancements": string[],
"negative_prompt_suggestions": string[]}}"""

FALLBACK: dict[str, Any] = {
    "operation": Operation.TEXT_TO_IMAGE.value,
    "steps": [{"name": "render", "detail": "按原始描述直接生成"}],
    "recommended_tier": QualityTier.STANDARD.value,
    "prompt_enhancements": [],
    "negative_prompt_suggestions": [],
}


def plan(
    session: Session,
    *,
    intent: str,
    source_params: dict[str, Any] | None = None,
    requested_operation: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    payload = {
        "intent": intent,
        "source_params": source_params or {},
        "requested_operation": requested_operation,
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=DEFAULT_SLOT,
    )

    # The user's explicit choice always wins over the model's suggestion.
    if requested_operation:
        outcome.data["operation"] = requested_operation
    if outcome.data.get("operation") not in {o.value for o in Operation}:
        outcome.data["operation"] = Operation.TEXT_TO_IMAGE.value
    if outcome.data.get("recommended_tier") not in {t.value for t in QualityTier}:
        outcome.data["recommended_tier"] = QualityTier.STANDARD.value
    enhancements = outcome.data.get("prompt_enhancements")
    outcome.data["prompt_enhancements"] = (
        [str(item)[:200] for item in enhancements[:8]] if isinstance(enhancements, list) else []
    )
    negatives = outcome.data.get("negative_prompt_suggestions")
    outcome.data["negative_prompt_suggestions"] = (
        [str(item)[:200] for item in negatives[:8]] if isinstance(negatives, list) else []
    )
    return outcome


CLARIFY_SLOT = "clarify"

QUESTION_KINDS = ("single_choice", "multi_choice", "free_text")
MAX_CLARIFY_QUESTIONS = 4
MAX_CLARIFY_OPTIONS = 6

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的创作规划顾问，在正式规划生成方案之前判断用户的意图描述
是否需要补充信息，才能规划出效果可靠的生成计划。
规则：
- 只有在缺少主体、场景、动作、镜头/构图、时长（视频时）这几类关键信息之一，
  且缺失会明显影响生成质量时才提问
- 描述已经具体、可以直接规划时，needs_clarification 为 false，questions 为空数组
- 每个问题只问一件事，问题数量不超过 {MAX_CLARIFY_QUESTIONS} 个，按对生成质量的影响从高到低排序
- kind 为 single_choice 或 multi_choice 时必须给 2 到 {MAX_CLARIFY_OPTIONS} 个
  具体、互斥或可组合的选项，不要给「其他」这类空泛选项
- kind 为 free_text 时 options 留空数组
- required 表示这个问题是否必须回答才能保证质量，不是强制用户必须点开
- 问题与选项用用户输入的语言书写

{JSON_INSTRUCTION}
格式：{{"needs_clarification": boolean, "questions": [{{"id": string,
"kind": "single_choice"|"multi_choice"|"free_text", "prompt": string,
"options": [{{"value": string, "label": string}}], "required": boolean}}]}}"""

CLARIFY_FALLBACK: dict[str, Any] = {"needs_clarification": False, "questions": []}


def clarify(
    session: Session,
    *,
    intent: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    job_id: str | None = None,
) -> AgentOutcome:
    """Judges whether an intent needs the author's input before planning.

    The fallback never blocks submission: a degraded or unparseable model
    call yields `needs_clarification=False`, so a gateway hiccup never
    becomes a dead end for the author (same reasoning as `copywriter.clarify`).
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({"intent": intent}, ensure_ascii=False),
        fallback=dict(CLARIFY_FALLBACK),
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=CLARIFY_SLOT,
    )
    questions = outcome.data.get("questions")
    outcome.data["questions"] = (
        [_sanitize_clarify_question(q) for q in questions[:MAX_CLARIFY_QUESTIONS]]
        if isinstance(questions, list)
        else []
    )
    outcome.data["questions"] = [q for q in outcome.data["questions"] if q is not None]
    outcome.data["needs_clarification"] = bool(outcome.data.get("needs_clarification")) and bool(
        outcome.data["questions"]
    )
    return outcome


def _sanitize_clarify_question(raw: Any) -> dict[str, Any] | None:
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
            for option in raw_options[:MAX_CLARIFY_OPTIONS]:
                if not isinstance(option, dict):
                    continue
                value = str(option.get("value") or "").strip()
                label = str(option.get("label") or "").strip()
                if value and label:
                    options.append({"value": value[:64], "label": label[:64]})
        if not options:
            return None

    return {
        "id": question_id[:64],
        "kind": kind,
        "prompt": question_prompt[:200],
        "options": options,
        "required": bool(raw.get("required")),
    }
