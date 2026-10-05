"""Which system prompts each agent role owns.

A role usually has exactly one system prompt, but not always. `intent_router`
is a single agent identity that makes two calls with completely unrelated
instructions — `classify()` picks a quality tier, `select_provider()` picks a
generation route — and `copy` likewise writes publication copy in one call and
polishes a scene description in another. Before slots existed both resolved
their prompt by role alone, so publishing one text silently overwrote the
other's instructions.

Slots belong to the *role*, not to the workflow node: `select_provider` is
invoked from the `route_score` node, which is not itself an agent node.

The first slot listed for a role is its primary one — that is where a
migration puts prompts published before slots existed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import AgentName

DEFAULT_SLOT = "default"


@dataclass(frozen=True, slots=True)
class PromptSlot:
    key: str
    label: str
    description: str


PROMPT_SLOTS: dict[str, tuple[PromptSlot, ...]] = {
    AgentName.SAFETY.value: (
        PromptSlot(DEFAULT_SLOT, "安全审核", "对生成请求与作品文本做内容安全判定。"),
    ),
    AgentName.PLANNER.value: (
        PromptSlot(DEFAULT_SLOT, "任务规划", "把用户意图拆解为可执行的生成计划。"),
        PromptSlot("clarify", "追问澄清", "生成前判断用户意图是否需要补充信息，并给出结构化问题。"),
        PromptSlot(
            "asset_plan",
            "图片资产规划",
            "为角色三视图/场景图/封面等图片资产规划提示词，兼顾同一角色多视角的一致性。",
        ),
        PromptSlot(
            "video_asset_plan",
            "视频资产规划",
            "为角色动作片段/转场/预告封面等视频资产规划提示词，兼顾镜头运镜与节奏。",
        ),
    ),
    AgentName.QUALITY.value: (
        PromptSlot(DEFAULT_SLOT, "质量评估", "判断生成结果是否达标、是否值得重试。"),
    ),
    AgentName.CANVAS_PLANNER.value: (
        PromptSlot(
            "canvas_generate_plan",
            "画布生成规划",
            "读取画布上选中卡片与其上游卡片，规划要生成的图片/视频任务。",
        ),
    ),
    AgentName.COPY.value: (
        PromptSlot("suggest", "作品文案", "为即将发布的作品生成标题、简介与标签。"),
        PromptSlot("enhance", "提示词润色", "在保留作者意图的前提下把画面描述写得更具体。"),
        PromptSlot(
            "clarify", "追问澄清", "在生成前判断画面描述是否需要用户补充信息，并给出结构化问题。"
        ),
        PromptSlot("script_draft", "剧本创作", "根据创意生成分场剧本，含场景、动作、运镜与对话。"),
        PromptSlot("script_revise", "剧本修改", "根据修改意见更新剧本，并给出本次修改摘要。"),
        PromptSlot(
            "blocking_route",
            "白膜调度判定",
            "判断白膜工作台的一条修改意见是否同时需要修改剧本，并拆分为剧本与白膜两条指令。",
        ),
        PromptSlot(
            "blocking_derive",
            "白膜预演",
            "把分场剧本搭成白膜预演：几何体场景、人偶走位与预设运镜，按目标总时长分配分镜段时长。",
        ),
        PromptSlot(
            "skill_match",
            "剧情技能匹配",
            "从戏码与情绪技能清单里挑出与这段剧情最相关的几条，供剧本创作与提示词润色参考。",
        ),
        PromptSlot(
            "character_describe",
            "角色设定整理",
            "根据引用该角色的剧本，为角色库角色整理可复用的角色描述与音色描述。",
        ),
    ),
    AgentName.INTENT_ROUTER.value: (
        PromptSlot("classify", "档位判定", "判断需求复杂度并建议生成档位，只降不升。"),
        PromptSlot(
            "select_provider",
            "供应商选型",
            "从已通过硬性能力过滤的候选里选出本次生成实际使用的供应商。",
        ),
    ),
    AgentName.EDITOR_PLANNER.value: (
        PromptSlot(
            "timeline_edit_plan",
            "时间线剪辑方案",
            "根据规范化时间线摘要产出可执行的 EditCommand 列表。",
        ),
    ),
}


def slots_for(role: str) -> tuple[PromptSlot, ...]:
    """Falls back to a single default slot so a role added to `AgentNode`
    before it gets an entry here is still editable."""
    return PROMPT_SLOTS.get(role) or (PromptSlot(DEFAULT_SLOT, role, ""),)


def primary_slot(role: str) -> str:
    return slots_for(role)[0].key


def is_known_slot(role: str, slot: str) -> bool:
    return any(candidate.key == slot for candidate in slots_for(role))
