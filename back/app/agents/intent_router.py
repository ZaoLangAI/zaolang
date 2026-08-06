"""Intent router agent: cheap, generic classification used to steer routing.

Distinct from `app/agents/router.py`, which stays pure-rule and never calls a
model. This agent only ever *suggests* a `quality_tier` for `route_score` to
pass into that pure scoring formula — it cannot touch the formula itself, and
`nodes._effective_tier` enforces that its suggestion may only downgrade, never
upgrade, what the user already paid for. Nothing here changes billing.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName, QualityTier

SYSTEM_PROMPT = f"""你是造浪平台的意图理解路由器。你的唯一职责是判断这次生成请求有多复杂，
从而建议一个够用就好、不浪费成本的生成档位。你的建议只能让档位降级，绝不能升级用户已付费选择的档位，
也完全不影响计费——只影响平台内部选哪条生成路线。
判断维度：
- complexity: 描述的具体程度、细节数量、是否有特殊构图/多主体/复杂运镜等要求
- 简单、常规的请求应建议更低档位以节省成本；复杂、精细的请求应建议保持原档位

{JSON_INSTRUCTION}
格式：{{"complexity": "simple" | "moderate" | "complex",
"suggested_quality_tier": "preview" | "standard" | "cinematic",
"cost_bias": number,
"rationale": string}}"""

# Safe default: never suggest a downgrade when the model is unavailable.
FALLBACK: dict[str, Any] = {
    "complexity": "moderate",
    "suggested_quality_tier": QualityTier.STANDARD.value,
    "cost_bias": 0.0,
    "rationale": "agent_unavailable",
}


def classify(
    session: Session,
    *,
    intent: str,
    params: dict[str, Any] | None = None,
    operation: str | None = None,
    requested_tier: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
) -> AgentOutcome:
    payload = {
        "intent": intent,
        "params": params or {},
        "operation": operation,
        "requested_tier": requested_tier,
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.INTENT_ROUTER,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=dict(
            FALLBACK, suggested_quality_tier=requested_tier or QualityTier.STANDARD.value
        ),
        job_id=job_id,
        user_id=user_id,
    )
    if outcome.data.get("suggested_quality_tier") not in {t.value for t in QualityTier}:
        outcome.data["suggested_quality_tier"] = requested_tier or QualityTier.STANDARD.value
    return outcome
