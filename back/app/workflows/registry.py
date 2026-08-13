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
    CopyGenerateConfig,
    CustomAgentStepConfig,
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
class AgentBinding:
    """Maps one config field onto the agent it selects.

    `role` is which role the bound agent must have, and it is what the
    console filters its picker by — a `safety_check` node may only run a
    safety agent, however many of those exist.

    `route_score` is why this is a list on the spec rather than a flag
    derived from `agent_role`: it is not an agent node, yet it runs an
    `intent_router` agent for the `select_provider` slot. The admin console
    reads these to render a picker instead of a raw text box, and
    `workflow_templates.service` reads them to validate a graph's bindings
    before publishing it.
    """

    config_field: str
    role: str
    slot: str


@dataclass(frozen=True, slots=True)
class DynamicAgentBinding:
    """An agent binding whose role is only known at run time.

    `custom_agent` exists precisely because its role is chosen in the console
    rather than fixed by the node type, so it cannot appear in
    `agent_bindings` — that list keys off a role known at code-review time.
    The role and slot live in sibling config fields named here, which is what
    lets the console render three cascading dropdowns instead of three raw
    text boxes, and lets `workflow_templates.service` check the combination
    before it is published.
    """

    config_field: str
    role_field: str
    slot_field: str


@dataclass(frozen=True, slots=True)
class NodeSpec:
    category: str
    # The Chinese `label`/`description` stay the source of truth for anything
    # server-side that has no locale (OpenAPI, logs, `shape.describe_workflow`).
    # The console renders `nodeType_<type>_label` / `_desc` out of its own
    # `adminWorkflows` messages instead, falling back to these — the back
    # office ships zh-CN and en, and a hardcoded Chinese palette left English
    # operators reading Chinese node names.
    label: str
    description: str
    config_schema: type[NodeConfig]
    executor: Executor
    output_ports: tuple[str, ...]
    is_agent: bool = False
    agent_role: str | None = None
    agent_bindings: tuple[AgentBinding, ...] = ()
    dynamic_agent_binding: DynamicAgentBinding | None = None
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
        agent_bindings=(AgentBinding("agent_id", "safety", "default"),),
        event_type=JobEventType.SAFETY,
    ),
    "skill_context": NodeSpec(
        category="context",
        label="创作技能上下文",
        description="若请求携带 skill_ids，把每个适用于当前操作类型的创作技能的"
        "参数模板（含 prompt）依次合并进 working params。",
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
        agent_bindings=(AgentBinding("agent_id", "planner", "default"),),
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
        agent_bindings=(AgentBinding("agent_id", "intent_router", "classify"),),
        event_type=JobEventType.INTENT_ROUTING,
    ),
    "custom_agent": NodeSpec(
        category="planning",
        label="自定义智能体判断",
        description="运行一个在管理台创建的判断类智能体，把结构化结论写入工作流状态供后续节点读取；"
        "不结算积分、不迁移任务状态。",
        config_schema=CustomAgentStepConfig,
        executor=nodes.execute_custom_agent_step,
        output_ports=("ok",),
        is_agent=True,
        # Fixed at runtime from `config.agent_role`: this node type exists
        # precisely because the role is not known at code-review time, so
        # neither `agent_role` nor `agent_bindings` can be declared here.
        agent_role=None,
        dynamic_agent_binding=DynamicAgentBinding(
            config_field="agent_id", role_field="agent_role", slot_field="slot"
        ),
        event_type=JobEventType.PROGRESS,
    ),
    "copy_generate": NodeSpec(
        category="generation",
        label="文案生成",
        description="运行文案智能体生成标题/简介/标签；开启「允许追问」时，"
        "遇到信息不足会暂停任务等待用户回答单选/多选/填写题，而不是直接输出。",
        config_schema=CopyGenerateConfig,
        executor=nodes.execute_copy_generate,
        output_ports=("ok",),
        is_agent=True,
        agent_role="copy",
        agent_bindings=(AgentBinding("agent_id", "copy", "suggest"),),
        event_type=JobEventType.AWAITING_INPUT,
    ),
    "route_score": NodeSpec(
        category="routing",
        label="路由打分",
        description="纯规则对候选供应商打分选路，不接大模型；重入次数受 max_attempts 约束。",
        config_schema=RouteScoreConfig,
        executor=nodes.execute_route_score,
        output_ports=("ok", "no_candidate", "retries_exhausted"),
        agent_bindings=(AgentBinding("selector_agent_id", "intent_router", "select_provider"),),
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
        agent_bindings=(AgentBinding("agent_id", "quality", "default"),),
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
