"""Safety agent.

Holds a hard veto: a rejection at any stage cannot be overturned by a later
agent or by routing. Only a human reviewer can supersede it, and the original
verdict stays on the record.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, run_agent
from app.models import ModerationResult
from app.models.base import utcnow
from app.models.enums import AgentName, ModerationStage, ModerationStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import ModerationConfig

SYSTEM_PROMPT = f"""你是造浪平台的内容安全审核器。平台面向 18 岁以上用户，
允许成人向的艺术表达，但必须严格拒绝以下内容：
- 任何涉及未成年人的性化描写
- 未获授权的真实人物换脸、裸露或诽谤性描绘
- 具体可执行的违法行为指导
- 仇恨、极端主义与恐怖主义宣传

判定为 reject 时，public_message 必须是给普通用户看的中文提示，不得复述违规内容本身。
不确定时返回 needs_review，不要放行。

{JSON_INSTRUCTION}
格式：{{"decision": "approve" | "needs_review" | "reject", "categories": string[],
"reason_code": string | null, "public_message": string}}"""

# Chosen so that an unparseable or unavailable model never silently approves.
FALLBACK: dict[str, Any] = {
    "decision": "needs_review",
    "categories": ["agent_unavailable"],
    "reason_code": "AGENT_UNAVAILABLE",
    "public_message": "内容需要人工复核，稍后会通知你结果。",
}


def review(
    session: Session,
    *,
    text: str,
    stage: ModerationStage,
    subject_type: str,
    subject_id: str,
    job_id: str | None = None,
    user_id: str | None = None,
) -> ModerationResult:
    """Runs a safety check and records the verdict.

    Operator-configured keywords are applied before the model, so an incident
    can be contained immediately without waiting for a model to learn.
    """
    config = config_service.get_typed(session, "moderation", ModerationConfig)
    blocked = _match_blocked_keyword(text, config.blocked_keywords)
    if blocked is not None:
        return _persist(
            session,
            stage=stage,
            subject_type=subject_type,
            subject_id=subject_id,
            status=ModerationStatus.REJECTED,
            categories={"matched_rule": "blocked_keyword"},
            reason_code="PROHIBITED_CONTENT",
            public_message="内容未通过安全检查，请调整描述后重试。",
            decided_by="rule",
            agent_run_id=None,
        )

    outcome = run_agent(
        session,
        agent_name=AgentName.SAFETY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=text,
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
    )

    decision = str(outcome.data.get("decision", "needs_review"))
    status = {
        "approve": ModerationStatus.APPROVED,
        "reject": ModerationStatus.REJECTED,
    }.get(decision, ModerationStatus.NEEDS_REVIEW)

    return _persist(
        session,
        stage=stage,
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        categories={"categories": outcome.data.get("categories", [])},
        reason_code=outcome.data.get("reason_code"),
        public_message=str(outcome.data.get("public_message") or ""),
        decided_by="agent",
        agent_run_id=outcome.agent_run_id,
    )


def _match_blocked_keyword(text: str, keywords: list[str]) -> str | None:
    lowered = text.lower()
    for keyword in keywords:
        if keyword and keyword.lower() in lowered:
            return keyword
    return None


def _persist(
    session: Session,
    *,
    stage: ModerationStage,
    subject_type: str,
    subject_id: str,
    status: ModerationStatus,
    categories: dict[str, Any],
    reason_code: str | None,
    public_message: str,
    decided_by: str,
    agent_run_id: str | None,
) -> ModerationResult:
    result = ModerationResult(
        stage=stage,
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        categories_json=categories,
        reason_code=reason_code,
        public_message=public_message or None,
        decided_by=decided_by,
        agent_run_id=agent_run_id,
        created_at=utcnow(),
    )
    session.add(result)
    session.flush()
    return result
