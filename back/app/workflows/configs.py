"""Per-node-type configuration schemas.

Split out from `registry.py` so `nodes.py` (the executors) and `registry.py`
(the type -> executor directory) can both depend on these without an import
cycle. Every schema is `extra="forbid"`, matching `platform_config.schemas`:
an admin's graph edit is rejected at parse time rather than silently ignoring
an unknown field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Every `agent_profile` field below names an `AgentProfile.key` under the
# node's role, so one operation can run a variant tuned for it while another
# keeps the default. `None` means "the role's default variant".
# `registry.NodeSpec.profile_bindings` is what tells the console which field
# maps to which role and slot; keep the two in step.


class SafetyCheckConfig(NodeConfig):
    agent_profile: str | None = Field(default=None, max_length=40)


class SkillContextConfig(NodeConfig):
    pass


class PlanningConfig(NodeConfig):
    agent_profile: str | None = Field(default=None, max_length=40)


class IntentRouterConfig(NodeConfig):
    agent_profile: str | None = Field(default=None, max_length=40)


class RouteScoreConfig(NodeConfig):
    # Routing has no agent node of its own: this node calls the
    # `intent_router` role's `select_provider` slot directly, so its variant
    # is bound here rather than on the `intent_router` node.
    selector_profile: str | None = Field(default=None, max_length=40)
    max_latency_ms: int | None = Field(default=None, ge=1_000, le=600_000)
    # How many times this node may be (re-)entered for one job before the
    # runner gives up and takes the `retries_exhausted` port instead of
    # running it again. Mirrors the old pipeline's `MAX_PROVIDER_ATTEMPTS`,
    # and is the single shared budget for both provider and quality retries,
    # since both loop back through this node.
    max_attempts: int = Field(default=2, ge=1, le=10)


class ProviderGenerateConfig(NodeConfig):
    # When False, a submit failure takes the `failed` port instead of
    # `retry`. The default template always retries through `route_score`, so
    # this only matters for a custom graph that wants a single-shot attempt.
    retry_on_failure: bool = True


class QualityCheckConfig(NodeConfig):
    agent_profile: str | None = Field(default=None, max_length=40)


class JoinConfig(NodeConfig):
    mode: Literal["barrier", "race"] = "barrier"
    # Ports counted as "this branch succeeded". `barrier` requires all
    # branches to land on one of these; `race` requires just one.
    success_ports: list[str] = Field(default_factory=lambda: ["succeeded", "pass", "ok"])


class SettleSuccessConfig(NodeConfig):
    pass


class FailConfig(NodeConfig):
    default_code: str = "PROVIDER_TEMPORARY_FAILURE"
    default_message: str = "生成失败，积分已退回。"


NODE_CONFIG_SCHEMAS: dict[str, type[NodeConfig]] = {
    "safety_check": SafetyCheckConfig,
    "skill_context": SkillContextConfig,
    "planning": PlanningConfig,
    "intent_router": IntentRouterConfig,
    "route_score": RouteScoreConfig,
    "provider_generate": ProviderGenerateConfig,
    "quality_check": QualityCheckConfig,
    "join": JoinConfig,
    "settle_success": SettleSuccessConfig,
    "fail": FailConfig,
}
