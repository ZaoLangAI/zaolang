"""The Generation Gateway team.

Agno's `Team` is what the AgentOS console exposes for interactive inspection:
an operator can talk to the gateway, watch each member reason, and see which
model every agent is currently bound to. It is deliberately *not* what runs
production jobs — `app.workers.pipeline` does that, in a fixed order, writing a
`JobEvent` at every step.

Keeping the two apart matters. The pipeline must be deterministic, resumable
and auditable; a team that decides its own delegation order is none of those.
The team therefore reads the same config bindings and the same whitelisted
tools, so what an operator observes matches what production does, without the
console becoming a way to run unaudited work.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agents import copywriter, planner, quality, safety
from app.agents.tools import build_toolkit
from app.llm import client as llm_client
from app.llm import failover
from app.models.enums import AgentName
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    AgentConfig,
    AgentModelBinding,
    LlmProviderConfig,
    LlmProviderEndpoint,
)

logger = logging.getLogger(__name__)

MEMBER_BRIEFS: dict[str, str] = {
    AgentName.SAFETY: safety.SYSTEM_PROMPT,
    AgentName.PLANNER: planner.SYSTEM_PROMPT,
    AgentName.QUALITY: quality.SYSTEM_PROMPT,
    AgentName.COPY: copywriter.SYSTEM_PROMPT,
}

TEAM_INSTRUCTIONS = """你是造浪生成网关的协调者，面向平台运营人员提供只读的推理观察能力。
- 安全判定由 Safety 成员给出，任何其他成员都不能推翻它。
- 你没有任何写权限：不能扣积分、不能发布作品、不能修改可见性或审核结论。
- 真正的生产任务由后台流水线按固定顺序执行，你的结论仅供人工参考。"""


def _resolve_endpoint(provider_config: LlmProviderConfig) -> LlmProviderEndpoint:
    """Picks the same primary/backup candidate `app/llm/client.py` would use.

    Every agent role shares the same `kind="general"` pool now. Raises rather
    than silently picking an arbitrary endpoint: an operator who enables the
    AgentOS console with an empty `llm_providers` pool needs a clear reason
    it failed to mount, not a confusing model error.
    """
    candidates = failover.general_candidates(provider_config)
    if not candidates:
        raise ValueError("未配置任何通用模型端点，无法构建 AgentOS 团队")
    return candidates[0][1]


def _model_for(binding: AgentModelBinding, endpoint: LlmProviderEndpoint) -> Any:
    from agno.models.openai.like import OpenAILike

    # `client_for_endpoint` already bakes base_url/api_key/timeout into the
    # OpenAI SDK client, so there is nothing left to configure here.
    return OpenAILike(
        id=binding.model,
        client=llm_client.client_for_endpoint(endpoint),
        max_tokens=binding.max_tokens,
        temperature=binding.temperature,
    )


def build_generation_gateway_team(session: Session) -> Any:
    """Assembles the team from the live config bindings.

    Built per call rather than cached at import: an operator who switches a
    model in the config centre expects the next inspection to use it.
    """
    from agno.agent import Agent
    from agno.team import Team

    config = config_service.get_typed(session, "agents", AgentConfig)
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)

    members: list[Any] = []
    for name, brief in MEMBER_BRIEFS.items():
        binding = config.bindings[name]
        toolkit = build_toolkit(session, name)
        endpoint = _resolve_endpoint(provider_config)
        members.append(
            Agent(
                name=name,
                model=_model_for(binding, endpoint),
                instructions=brief,
                # Only the whitelist; an agent cannot reach a domain service
                # that would move credits or change visibility.
                tools=list(toolkit.values()) or None,
            )
        )

    planner_binding = config.bindings[AgentName.PLANNER]
    planner_endpoint = _resolve_endpoint(provider_config)
    return Team(
        name="generation_gateway",
        members=members,
        model=_model_for(planner_binding, planner_endpoint),
        instructions=TEAM_INSTRUCTIONS,
    )
