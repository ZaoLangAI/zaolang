"""The catalogue an operator picks a new agent's role from.

An agent is created by hand in the console, but its *role* is not free text:
it is chosen from this list. Two reasons it stays a code-maintained
directory rather than a table:

* a role only does something if code invokes it — the built-in five are
  invoked by their own workflow node types, and anything else needs the
  generic `custom_agent` node — so "any string an operator types" would
  produce agents that can never run;
* the `operations` on a preset is what filters the media-candidate picker
  for creative agents, and a wrong value there would let an operator wire a
  text-to-image endpoint into a video agent.

`category` decides which half of the console's create form applies:
`judgment` agents bind one LLM model (plus an optional backup),
`creative` agents bind several media endpoints with a cost weight each.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models.enums import AgentName, Operation

AgentCategory = Literal["judgment", "creative"]

JUDGMENT: AgentCategory = "judgment"
CREATIVE: AgentCategory = "creative"


@dataclass(frozen=True, slots=True)
class RolePreset:
    role: str
    display_name: str
    category: AgentCategory
    description: str = ""
    # Empty means general purpose: a judgment agent is not tied to any single
    # operation. For creative roles this is the set the media-candidate picker
    # filters by, and it is copied onto `AgentProfile.operations_json`.
    operations: tuple[str, ...] = ()
    # Which `SKILL_TEMPLATES` entry the console pre-selects. `None` means the
    # role has no shipped starting prompt.
    default_template_key: str | None = None
    # Display order in the console's role dropdown.
    sort_order: int = 0


_VIDEO_OPERATIONS = (
    Operation.TEXT_TO_VIDEO.value,
    Operation.IMAGE_TO_VIDEO.value,
    Operation.VIDEO_TO_VIDEO.value,
)
_IMAGE_OPERATIONS = (Operation.TEXT_TO_IMAGE.value, Operation.IMAGE_TO_IMAGE.value)


ROLE_PRESETS: tuple[RolePreset, ...] = (
    RolePreset(
        role=AgentName.SAFETY.value,
        display_name="安全审核",
        category=JUDGMENT,
        description="内容安全一票否决，拒绝后不可被下游节点覆盖。",
        default_template_key="safety-default",
        sort_order=0,
    ),
    RolePreset(
        role=AgentName.PLANNER.value,
        display_name="任务规划",
        category=JUDGMENT,
        description="把用户意图拆解为可执行的生成计划。",
        default_template_key="planner-default",
        sort_order=1,
    ),
    RolePreset(
        role=AgentName.QUALITY.value,
        display_name="质量评估",
        category=JUDGMENT,
        description="评估生成结果是否达标、是否值得重试。",
        default_template_key="quality-default",
        sort_order=2,
    ),
    RolePreset(
        role=AgentName.COPY.value,
        display_name="文案生成",
        category=JUDGMENT,
        description="生成标题、简介与标签，或润色画面描述。",
        default_template_key="copy-suggest",
        sort_order=3,
    ),
    RolePreset(
        role=AgentName.INTENT_ROUTER.value,
        display_name="意图理解路由",
        category=JUDGMENT,
        description="判断需求复杂度建议生成档位（只降不升），并在候选中选出本次生成路线。",
        default_template_key="intent-router-classify",
        sort_order=4,
    ),
    RolePreset(
        role="image_creative",
        display_name="图片创作",
        category=CREATIVE,
        description="按内容与成本权衡挑选图片生成路线的创作智能体。",
        operations=_IMAGE_OPERATIONS,
        default_template_key="creative-brief",
        sort_order=10,
    ),
    RolePreset(
        role="video_creative",
        display_name="视频创作",
        category=CREATIVE,
        description="按内容与成本权衡挑选视频生成路线的创作智能体。",
        operations=_VIDEO_OPERATIONS,
        default_template_key="creative-brief",
        sort_order=11,
    ),
    RolePreset(
        role="audio_creative",
        display_name="语音创作",
        category=CREATIVE,
        description="按内容与成本权衡挑选语音生成路线的创作智能体。",
        operations=(Operation.AUDIO_GENERATION.value,),
        default_template_key="creative-brief",
        sort_order=12,
    ),
)

_BY_ROLE: dict[str, RolePreset] = {preset.role: preset for preset in ROLE_PRESETS}

# A role row that predates this catalogue (or one seeded by a future preset
# that was later removed) still has to render somewhere in the console.
FALLBACK_CATEGORY: AgentCategory = JUDGMENT


def all_presets() -> tuple[RolePreset, ...]:
    return tuple(sorted(ROLE_PRESETS, key=lambda preset: (preset.sort_order, preset.role)))


def find(role: str) -> RolePreset | None:
    return _BY_ROLE.get(role)


def category_for(role: str) -> AgentCategory:
    preset = _BY_ROLE.get(role)
    return preset.category if preset is not None else FALLBACK_CATEGORY


def operations_for(role: str) -> list[str]:
    preset = _BY_ROLE.get(role)
    return list(preset.operations) if preset is not None else []


def is_creative(role: str) -> bool:
    return category_for(role) == CREATIVE


def known_roles() -> set[str]:
    return set(_BY_ROLE)
