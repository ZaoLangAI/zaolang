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


# Every `agent_id` field below names one agent (`AgentProfile.id`) whose role
# must match the node's, so one operation can run an agent tuned for it while
# another keeps the role's default. `None` means "the role's default agent".
# `registry.NodeSpec.agent_bindings` is what tells the console which field
# takes which role and slot; keep the two in step.
#
# An id rather than a name: an operator may rename an agent at any time, and a
# published graph must keep pointing at the same one.


class SafetyCheckConfig(NodeConfig):
    agent_id: str | None = Field(default=None, max_length=40)


class SkillContextConfig(NodeConfig):
    pass


class PlanningConfig(NodeConfig):
    """Runs the planner agent's plan slot.

    `allow_followup_question` defaults to `True`: a graph left without this
    field explicitly set (every existing graph, including the seeded default
    one) gets reverse-questioning for free the moment this ships. Setting it
    to `False` on a specific graph opts back out to the pre-existing
    behaviour. Mirrors `CopyGenerateConfig`'s `allow_followup_question` /
    `output_key` shape so the two suspend-capable planning-stage nodes stay
    easy to compare.
    """

    agent_id: str | None = Field(default=None, max_length=40)
    output_key: str = Field(default="plan", min_length=1, max_length=40)
    allow_followup_question: bool = True


class IntentRouterConfig(NodeConfig):
    agent_id: str | None = Field(default=None, max_length=40)


class AssetPlanningConfig(NodeConfig):
    """Runs the planner agent's `asset_plan` slot for an image or video asset job.

    Only meaningful when `ctx.params["asset_kind"]`/`ctx.params["video_asset_kind"]`
    is a non-`GENERAL` `ImageAssetKind`/`VideoAssetKind` — see `asset_graph`
    (`app.workflows.defaults`), the only place this node type is wired in
    today. A `GENERAL` job (or one with neither set) is a no-op
    pass-through, so a graph that accidentally includes this node for plain
    generation degrades gracefully instead of erroring.
    """

    agent_id: str | None = Field(default=None, max_length=40)
    output_key: str = Field(default="asset_plan", min_length=1, max_length=40)


class AssetOutputAdvanceConfig(NodeConfig):
    """Records one iteration's output and decides whether to loop back.

    Sits between `quality_check` and `asset_output_link` in `asset_graph`
    (`app.workflows.defaults`). A no-op single pass for `scene`/`cover`/
    `general` image jobs and every video kind — only an image `CHARACTER`-
    kind job whose `GenerationParams.character_views` names more than one
    view actually loops, back to `asset_planning`, once per remaining view.
    See `app.workflows.nodes.execute_asset_output_advance`.
    """


class AssetOutputLinkConfig(NodeConfig):
    """Attaches a succeeded image/video job's output to its target character/scene.

    Runs after `quality_check` passes: `ctx.state["asset_id"]` must already
    be set. A job whose asset kind is `GENERAL` (or image `COVER`/video
    `TRANSITION`/`COVER`) is a no-op; image `CHARACTER`/`SCENE` and video
    `CHARACTER_ACTION`/`SCENE` with no `target_character_id`/
    `target_scene_id` auto-creates a brand-new skill instead of leaving the
    output unattached — see `app.workflows.nodes.execute_asset_output_link`.
    """

    # When true and `asset_kind` is a character view with no
    # `target_character_id`, creates a brand-new character skill from the
    # plan's subject instead of leaving the output unlinked.
    auto_create_character: bool = True
    # Same idea, one asset kind over: when true and `asset_kind == SCENE`
    # with no `target_scene_id`, creates a brand-new scene skill instead of
    # leaving the output unattached. Kept as its own flag (rather than
    # reusing `auto_create_character`) so a future caller can turn one off
    # without the other.
    auto_create_scene: bool = True
    # A `prop` job with no `target_prop_id` creates a prop card (AC-4).
    auto_create_prop: bool = True


class CustomAgentStepConfig(NodeConfig):
    """Runs an operator-created judgment role.

    Unlike every other agent node type, the role is not fixed by the node
    type: it is named here, because the whole point is to run a role that
    was created in the console rather than shipped in `registry.py`. The
    result lands in `ctx.state[output_key]` and has no other effect.
    """

    agent_role: str = Field(min_length=1, max_length=40)
    agent_id: str | None = Field(default=None, max_length=40)
    slot: str = Field(default="default", min_length=1, max_length=40)
    output_key: str = Field(default="custom_agent", min_length=1, max_length=40)


class CopyGenerateConfig(NodeConfig):
    """Runs the copy agent's title/description/tags suggestion.

    `agent_id` is bound to the `copy` role's `suggest` slot (see
    `registry.NODE_TYPES["copy_generate"].agent_bindings`); the same agent's
    `clarify` slot is what `allow_followup_question` opts into, so one
    binding covers both calls this node type makes.
    """

    agent_id: str | None = Field(default=None, max_length=40)
    output_key: str = Field(default="copy_suggestion", min_length=1, max_length=40)
    # When true, the node also runs the copy agent's `clarify` slot and, if
    # it judges the description worth a follow-up, suspends the job at
    # `AWAITING_INPUT` instead of moving straight on. When false this node
    # behaves like a plain suggestion step that never pauses the job.
    allow_followup_question: bool = False


class RouteScoreConfig(NodeConfig):
    # Routing has no agent node of its own: this node calls the
    # `intent_router` role's `select_provider` slot directly, so the agent
    # running that slot is bound here rather than on the `intent_router` node.
    selector_agent_id: str | None = Field(default=None, max_length=40)
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


class VideoAnalysisGenerateConfig(NodeConfig):
    """`video_analysis`'s own generate node — see
    `app.workflows.nodes.execute_video_analysis_generate`. Mirrors
    `ProviderGenerateConfig`'s one knob; there is no separate quality-check
    retry path for this operation since it has no `quality_check` step."""

    retry_on_failure: bool = True


class QualityCheckConfig(NodeConfig):
    agent_id: str | None = Field(default=None, max_length=40)


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
    "asset_planning": AssetPlanningConfig,
    "custom_agent": CustomAgentStepConfig,
    "copy_generate": CopyGenerateConfig,
    "route_score": RouteScoreConfig,
    "provider_generate": ProviderGenerateConfig,
    "video_analysis_generate": VideoAnalysisGenerateConfig,
    "quality_check": QualityCheckConfig,
    "asset_output_advance": AssetOutputAdvanceConfig,
    "asset_output_link": AssetOutputLinkConfig,
    "join": JoinConfig,
    "settle_success": SettleSuccessConfig,
    "fail": FailConfig,
}
