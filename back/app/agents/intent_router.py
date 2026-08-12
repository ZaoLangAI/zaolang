"""Intent router agent.

Two independent LLM calls share this module, the same `intent_router` agent
identity and the same model binding — but they never run in the same turn
and never share a system prompt:

- `classify()` — cheap, generic classification: how complex is this request,
  and can the user's chosen quality tier be safely downgraded to save cost?
  Its suggestion can only ever lower the tier the user already paid for
  (`app.workflows.nodes._effective_tier` enforces that) and never touches
  which provider gets used. It also emits `cost_bias`, a request-level "how
  cost-sensitive is this one" signal that `select_provider()` receives purely
  as context (see below) — `classify()` itself never reads it back.

- `select_provider()` — the actual routing decision. Given the operation and
  quality tier already settled, plus every candidate that survived
  `app.agents.router.route`'s hard eligibility filter (capability, tier,
  enabled state, latency budget), it picks the one to use and explains why.
  `router.py` no longer has a scoring formula of its own: this call *is* the
  choice, not a suggestion layered on top of one. `classify()`'s `cost_bias`
  rides along as context — informational only, never a coefficient applied
  in code.

Neither call moves credits or talks to a provider directly, but they are not
equally advisory: `classify`'s output only ever narrows a tier, while
`select_provider`'s output is the routing decision itself. If it is
unavailable or returns a provider outside the eligible set, `router.route`
reports no selection — there is no formula to fall back to.

Because the two share an agent identity, each names its own prompt *slot*
when resolving a published `AgentSkill`. Without that, publishing one of
these prompts from the console would overwrite the other's instructions.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName, QualityTier

CLASSIFY_SLOT = "classify"
SELECT_PROVIDER_SLOT = "select_provider"

SYSTEM_PROMPT = f"""你是造浪平台的意图理解路由器。你的唯一职责是判断这次生成请求有多复杂，
从而建议一个够用就好、不浪费成本的生成档位。你的建议只能让档位降级，绝不能升级用户已付费选择的档位，
也完全不影响计费——只影响平台内部选哪条生成路线。
判断维度：
- complexity 对图片类操作（text_to_image / image_to_image）：描述的具体程度、细节数量、
  是否有特殊构图/多主体/复杂运镜等要求
- complexity 对视频类操作（text_to_video / image_to_video / video_to_video）：文字描述本身可能很短，
  但视频的复杂度主要看内容而不是字数——多主体是否有同步/对抗性动作（如打斗、追逐、人群互动）、
  是否要求动作连贯或运动幅度大、是否要求写实的物理/光影一致性、镜头是否需要多次切换或复杂运镜。
  这些即使描述简短也应该判为 moderate 甚至 complex，不要因为文字少就默认判 simple
- 简单、常规的请求应建议更低档位以节省成本；复杂、精细的请求应建议保持原档位
- cost_bias: 0 到 1 之间的小数，表示这次请求本身有多适合往省成本的方向倾斜——
  0 表示应该优先保证效果，不要为了省成本牺牲质量；1 表示内容对渲染精细度不敏感，
  可以明显偏向更省成本的路线；不确定时给 0.5。这个信号会作为参考传给后续的供应商选型，
  不是硬性指标。

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
    agent_id: str | None = None,
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
        agent_id=agent_id,
        slot=CLASSIFY_SLOT,
    )
    if outcome.data.get("suggested_quality_tier") not in {t.value for t in QualityTier}:
        outcome.data["suggested_quality_tier"] = requested_tier or QualityTier.STANDARD.value
    return outcome


SELECT_PROVIDER_SYSTEM_PROMPT = f"""你是造浪平台的生成路线选择器。你会收到这次生成请求的操作类型、
质量档位，以及一份已经过硬性能力过滤的候选供应商列表——列表里的每一个都真实支持这个操作和这个档位，
你只需要从中选出最合适的一个，不需要也不允许再做能力过滤。
综合考虑每个候选自带的信息：
- quality_prior：供应商产出质量的先验评估
- success_rate：近期实际观测到的成功率（样本不足时已经用保守先验兜底，数值本身可信）
- avg_latency_ms：平均延迟
- effective_cost：已经把重试放大后的有效成本
- cost_bias：整次请求级别（不是逐个候选）的成本倾向参考，来自意图判档的结果，
  只在部分请求里出现。越接近 1 越可以放心选更省成本的候选，越接近 0 越应该优先选效果更好的候选，
  同样是参考不是硬性指标。
只能从给定列表的 provider 字段里原样选一个，不要编造列表之外的名字。

{JSON_INSTRUCTION}
格式：{{"selected_provider": string, "rationale": string}}"""

# No fallback pick: an unparseable or unavailable response must not silently
# choose a provider. The caller (`router.route`) treats a missing/invalid
# `selected_provider` exactly like "no eligible provider" — there is no
# formula left to fall back to.
SELECT_PROVIDER_FALLBACK: dict[str, Any] = {
    "selected_provider": None,
    "rationale": "agent_unavailable",
}


def select_provider(
    session: Session,
    *,
    operation: str,
    quality_tier: str,
    candidates: list[dict[str, Any]],
    cost_bias: float | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Picks one provider from an already hard-filtered eligible list.

    `candidates` must already be restricted to providers that can serve
    `operation`/`quality_tier` at all — this call never re-checks capability,
    only chooses among options that are all technically valid.

    `cost_bias` is `classify()`'s request-level cost signal, forwarded here as
    context for the model to weigh, never a coefficient this function applies
    itself. Omitted entirely when the caller has none (e.g. no `classify()`
    ran).
    """
    payload: dict[str, Any] = {
        "operation": operation,
        "quality_tier": quality_tier,
        "candidates": candidates,
    }
    if cost_bias is not None:
        payload["cost_bias"] = cost_bias
    return run_agent(
        session,
        agent_name=AgentName.INTENT_ROUTER,
        system_prompt=SELECT_PROVIDER_SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=SELECT_PROVIDER_FALLBACK,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=SELECT_PROVIDER_SLOT,
    )
