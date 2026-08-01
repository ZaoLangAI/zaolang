"""Planner agent: turns an intent into an executable generation plan."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName, Operation, QualityTier

SYSTEM_PROMPT = f"""你是造浪平台的创作规划器。根据用户意图与来源作品参数，产出一个可执行的生成计划。
规则：
- operation 只能是 text_to_image / text_to_video / image_to_video / video_to_video
- 若用户没有明确要求高质量，优先推荐 standard 档位以控制成本
- prompt_enhancements 是对原始描述的补充，不要改变用户的核心意图
- 不要编造用户没有提供的素材

{JSON_INSTRUCTION}
格式：{{"operation": string, "steps": [{{"name": string, "detail": string}}],
"recommended_tier": "preview"|"standard"|"cinematic", "prompt_enhancements": string[]}}"""

FALLBACK: dict[str, Any] = {
    "operation": Operation.TEXT_TO_IMAGE.value,
    "steps": [{"name": "render", "detail": "按原始描述直接生成"}],
    "recommended_tier": QualityTier.STANDARD.value,
    "prompt_enhancements": [],
}


def plan(
    session: Session,
    *,
    intent: str,
    source_params: dict[str, Any] | None = None,
    requested_operation: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
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
    )

    # The user's explicit choice always wins over the model's suggestion.
    if requested_operation:
        outcome.data["operation"] = requested_operation
    if outcome.data.get("operation") not in {o.value for o in Operation}:
        outcome.data["operation"] = Operation.TEXT_TO_IMAGE.value
    if outcome.data.get("recommended_tier") not in {t.value for t in QualityTier}:
        outcome.data["recommended_tier"] = QualityTier.STANDARD.value
    return outcome
