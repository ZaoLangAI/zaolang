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
    ),
    AgentName.QUALITY.value: (
        PromptSlot(DEFAULT_SLOT, "质量评估", "判断生成结果是否达标、是否值得重试。"),
    ),
    AgentName.COPY.value: (
        PromptSlot("suggest", "作品文案", "为即将发布的作品生成标题、简介与标签。"),
        PromptSlot("enhance", "提示词润色", "在保留作者意图的前提下把画面描述写得更具体。"),
        PromptSlot("clarify", "追问澄清", "在生成前判断画面描述是否需要用户补充信息，并给出结构化问题。"),
    ),
    AgentName.INTENT_ROUTER.value: (
        PromptSlot("classify", "档位判定", "判断需求复杂度并建议生成档位，只降不升。"),
        PromptSlot(
            "select_provider",
            "供应商选型",
            "从已通过硬性能力过滤的候选里选出本次生成实际使用的供应商。",
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
