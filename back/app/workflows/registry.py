"""The node type directory: a whitelist of code-reviewed node executors.

This is the "predefined node palette" an operator drags from in the editor —
analogous to ComfyUI's built-in node catalog. There is no way to add a node
type from the admin console; every entry here shipped in a code review.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models.enums import JobEventType
from app.workflows import nodes
from app.workflows.configs import (
    FailConfig,
    IntentRouterConfig,
    JoinConfig,
    NodeConfig,
    PlanningConfig,
    ProviderGenerateConfig,
    QualityCheckConfig,
    RouteScoreConfig,
    SafetyCheckConfig,
    SettleSuccessConfig,
    SkillContextConfig,
)
from app.workflows.types import NodeResult, WorkflowContext

# Each concrete executor takes its own `NodeConfig` subclass, not the base
# type — Callable parameters are contravariant, so `Any` is the pragmatic
# choice here rather than fighting variance for a registry keyed by string;
# `_execute_node` (`runner.py`) is what actually pairs a node's real config
# type with its executor via `config_schema.model_validate(...)`.
Executor = Callable[[WorkflowContext, Any], NodeResult]


@dataclass(frozen=True, slots=True)
class NodeSpec:
    category: str
    label: str
    description: str
    config_schema: type[NodeConfig]
    executor: Executor
    output_ports: tuple[str, ...]
    is_agent: bool = False
    agent_role: str | None = None
    # The `JobEvent` this node writes on its way through, if any — used only
    # to derive the ops console's declared timeline (`workflows/shape.py`).
    # `None` for nodes with no single representative public event
    # (`skill_context`, `join`) or whose event only fires on the failure
    # path (`fail`, which the timeline's happy-path walk never reaches).
    event_type: JobEventType | None = None


NODE_TYPES: dict[str, NodeSpec] = {
    "safety_check": NodeSpec(
        category="moderation",
        label="安全审核",
        description="内容安全一票否决，拒绝后不可被下游节点覆盖。",
        config_schema=SafetyCheckConfig,
        executor=nodes.execute_safety_check,
        output_ports=("pass", "reject"),
        is_agent=True,
        agent_role="safety",
        event_type=JobEventType.SAFETY,
    ),
    "skill_context": NodeSpec(
        category="context",
        label="创作技能上下文",
        description="若请求携带 skill_id，把该创作技能的参数模板合并进 working params，"
        "并登记一次使用。",
        config_schema=SkillContextConfig,
        executor=nodes.execute_skill_context,
        output_ports=("ok",),
    ),
    "planning": NodeSpec(
        category="planning",
        label="任务规划",
        description="把用户意图拆解为可执行的生成计划。",
        config_schema=PlanningConfig,
        executor=nodes.execute_planning,
        output_ports=("ok",),
        is_agent=True,
        agent_role="planner",
        event_type=JobEventType.PLANNING,
    ),
    "intent_router": NodeSpec(
        category="planning",
        label="意图理解路由",
        description="用低成本通用智能体判断需求复杂度，只能把生成档位向下调整，为路由打分提供提示，不参与计费。",
        config_schema=IntentRouterConfig,
        executor=nodes.execute_intent_router,
        output_ports=("ok",),
        is_agent=True,
        agent_role="intent_router",
        event_type=JobEventType.INTENT_ROUTING,
    ),
    "route_score": NodeSpec(
        category="routing",
        label="路由打分",
        description="纯规则对候选供应商打分选路，不接大模型；重入次数受 max_attempts 约束。",
        config_schema=RouteScoreConfig,
        executor=nodes.execute_route_score,
        output_ports=("ok", "no_candidate", "retries_exhausted"),
        event_type=JobEventType.ROUTING,
    ),
    "provider_generate": NodeSpec(
        category="generation",
        label="供应商生成",
        description="向选中的供应商发起一次生成尝试；内置取消检查，"
        "失败时不进入该节点的 failed 分支就走 retry。",
        config_schema=ProviderGenerateConfig,
        executor=nodes.execute_provider_generate,
        output_ports=("succeeded", "retry", "failed"),
        event_type=JobEventType.GENERATING,
    ),
    "quality_check": NodeSpec(
        category="quality",
        label="质量评估",
        description="评估输出是否达标；通过时登记产出资产与实际结算积分。",
        config_schema=QualityCheckConfig,
        executor=nodes.execute_quality_check,
        output_ports=("pass", "retry", "fail"),
        is_agent=True,
        agent_role="quality",
        event_type=JobEventType.QUALITY_CHECK,
    ),
    "join": NodeSpec(
        category="control",
        label="并行汇合",
        description="汇合 fan-out 出的并行分支：barrier 要求全部分支成功，"
        "race 只要有一支成功即可。",
        config_schema=JoinConfig,
        executor=nodes.execute_join,
        output_ports=("ok", "partial_failure"),
    ),
    "settle_success": NodeSpec(
        category="terminal",
        label="成功结算",
        description="唯一允许结算成功积分并把任务迁移到成功终态的节点类型。",
        config_schema=SettleSuccessConfig,
        executor=nodes.execute_settle_success,
        output_ports=(),
        event_type=JobEventType.SUCCEEDED,
    ),
    "fail": NodeSpec(
        category="terminal",
        label="失败终止",
        description="唯一允许释放预扣积分并把任务迁移到失败终态的节点类型。",
        config_schema=FailConfig,
        executor=nodes.execute_fail,
        output_ports=(),
    ),
}


def parse_config(node_type: str, raw: dict | None) -> NodeConfig:
    spec = NODE_TYPES[node_type]
    return spec.config_schema.model_validate(raw or {})
