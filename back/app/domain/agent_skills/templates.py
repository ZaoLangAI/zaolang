"""Starting prompts an operator can load into the skill editor.

Creating an agent in the console and leaving its prompt empty produces a
agent that silently inherits the role default — which looks like it works
until the day someone edits the default. A template gives the operator a
real, reviewed starting text instead.

Loading a template only fills the editor. Publishing is still a separate,
confirmed action (`POST /agent-skills`), because the published prompt is what
decides whether content is rejected or credits get spent on a retry.

The built-in five roles' templates are their own modules' `SYSTEM_PROMPT`
constants, imported rather than copied: a template that drifts from the code
default would quietly change behaviour the first time someone loads it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents import (
    canvas_planner,
    copywriter,
    custom,
    editor_planner,
    intent_router,
    planner,
    quality,
    safety,
)
from app.agents.slots import DEFAULT_SLOT
from app.domain.agent_skills.presets import ASSIST, JUDGMENT, AgentCategory


@dataclass(frozen=True, slots=True)
class SkillTemplate:
    key: str
    label: str
    description: str
    category: AgentCategory
    prompt_template: str
    tool_grants: tuple[str, ...] = ()
    # `None` means the template suits any role in its category.
    role: str | None = None
    slot: str = DEFAULT_SLOT
    # Which copy request-routing bucket this starting prompt is written for.
    # `None` means it is a generic fallback on that slot (e.g. `copy-enhance`).
    asset_kind: str | None = None


_GENERIC_CLASSIFY = """你是造浪平台的内容分类器。把输入内容归入下列类别之一，并说明依据。
类别：{{在这里列出你的类别，例如 tutorial / showcase / experiment}}
规则：
- 只能返回上面列出的类别之一，不要自创类别
- confidence 是 0 到 1 的小数，证据不足时给低分而不是硬选一个
- notes 用一两句话说明判断依据

只输出一个 JSON 对象，不要输出任何解释、前言或 Markdown 代码块标记。
格式：{"verdict": string, "confidence": number, "notes": string}"""

_GENERIC_SCORE = """你是造浪平台的结构化评分器。按下列维度为输入内容打分。
维度（均为 0 到 1 的小数）：
- relevance：与目标的相关程度
- craft：完成度与技术质量
- originality：新意

规则：
- 分数要能被 notes 里的具体理由支撑，不要给没有依据的高分
- verdict 在总体可用时为 pass，明显不可用时为 fail

只输出一个 JSON 对象，不要输出任何解释、前言或 Markdown 代码块标记。
格式：{"verdict": "pass"|"fail", "scores": {"relevance": number, "craft": number,
"originality": number}, "notes": string}"""

SKILL_TEMPLATES: tuple[SkillTemplate, ...] = (
    SkillTemplate(
        key="safety-default",
        label="安全审核 · 平台默认",
        description=(
            "当前代码内置的安全审核提示词，18+ 艺术表达放行、未成年人性化等一票否决，"
            "写实暴力/血腥内容转人工复核。"
        ),
        category=JUDGMENT,
        prompt_template=safety.SYSTEM_PROMPT,
        role="safety",
    ),
    SkillTemplate(
        key="planner-default",
        label="任务规划 · 平台默认",
        description="把用户意图拆成可执行生成计划，默认倾向 standard 档位控制成本。",
        category=JUDGMENT,
        prompt_template=planner.SYSTEM_PROMPT,
        tool_grants=("price_operation", "list_provider_capabilities", "lookup_source_parameters"),
        role="planner",
    ),
    SkillTemplate(
        key="planner-clarify",
        label="任务规划 · 追问澄清",
        description="生成前判断用户意图是否需要补充信息，并给出结构化问题。",
        category=JUDGMENT,
        prompt_template=planner.CLARIFY_SYSTEM_PROMPT,
        role="planner",
        slot=planner.CLARIFY_SLOT,
    ),
    SkillTemplate(
        key="planner-asset-plan",
        label="任务规划 · 图片资产规划",
        description="为角色设定图/场景图/封面规划提示词；角色 front 是一张多分区设定图，side/back 仍是单视角。",
        category=JUDGMENT,
        prompt_template=planner.ASSET_PLAN_SYSTEM_PROMPT,
        role="planner",
        slot=planner.ASSET_PLAN_SLOT,
    ),
    SkillTemplate(
        key="quality-default",
        label="质量评估 · 平台默认",
        description="三维打分并判断是否值得重试；重试会额外消耗积分，默认从宽。",
        category=JUDGMENT,
        prompt_template=quality.SYSTEM_PROMPT,
        role="quality",
    ),
    SkillTemplate(
        key="copy-suggest",
        label="文案生成 · 作品文案",
        description="为即将发布的作品流卡片写标题、简介与检索标签，remix 时点出来源关系。",
        category=ASSIST,
        prompt_template=copywriter.SYSTEM_PROMPT,
        tool_grants=("suggest_tags",),
        role="copy",
        slot=copywriter.SUGGEST_SLOT,
        asset_kind="copy",
    ),
    SkillTemplate(
        key="copy-enhance",
        label="文案生成 · 提示词润色",
        description="通用画面描述的诊断式润色，未指定角色设定图、场景空镜或封面海报时使用。",
        category=ASSIST,
        prompt_template=copywriter.ENHANCE_SYSTEM_PROMPT,
        role="copy",
        slot=copywriter.ENHANCE_SLOT,
    ),
    SkillTemplate(
        key="copy-enhance-character",
        label="文案润色 · 角色",
        description="角色设定图教练：把同一个人写成一张多分区设定图（左三视图、右特写与色板），禁止改回单视角。",
        category=ASSIST,
        prompt_template=copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER,
        role="copy",
        slot=copywriter.ENHANCE_SLOT,
        asset_kind="character",
    ),
    SkillTemplate(
        key="copy-enhance-cover",
        label="文案润色 · 封面",
        description="封面海报教练：单一主视觉、缩略图可读，并预留标题安全区。",
        category=ASSIST,
        prompt_template=copywriter.ENHANCE_SYSTEM_PROMPT_COVER,
        role="copy",
        slot=copywriter.ENHANCE_SLOT,
        asset_kind="cover",
    ),
    SkillTemplate(
        key="copy-enhance-scene",
        label="文案润色 · 场景",
        description=(
            "场景空镜教练：单一机位、遮挡成立、锁年代与媒介，"
            "按空间类型挑技能包润色，并在信息不足时追问作者。"
        ),
        category=ASSIST,
        prompt_template=copywriter.ENHANCE_SYSTEM_PROMPT_SCENE,
        role="copy",
        slot=copywriter.ENHANCE_SLOT,
        asset_kind="scene",
    ),
    SkillTemplate(
        key="copy-clarify",
        label="文案生成 · 追问澄清",
        description="生成前判断画面描述是否需要补充信息，并给出结构化问题。",
        category=ASSIST,
        prompt_template=copywriter.CLARIFY_SYSTEM_PROMPT,
        role="copy",
        slot=copywriter.CLARIFY_SLOT,
    ),
    SkillTemplate(
        key="copy-script-draft",
        label="文案生成 · 剧本创作",
        description="根据创意生成完整分场短剧剧本，含场景、动作、运镜、对话与建议切分点。",
        category=ASSIST,
        prompt_template=copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT,
        role="copy",
        slot=copywriter.SCRIPT_DRAFT_SLOT,
    ),
    SkillTemplate(
        key="copy-script-revise",
        label="文案生成 · 剧本修改",
        description="根据修改意见更新剧本并给出本次修改摘要，同步维护建议切分点。",
        category=ASSIST,
        prompt_template=copywriter.SCRIPT_REVISE_SYSTEM_PROMPT,
        role="copy",
        slot=copywriter.SCRIPT_REVISE_SLOT,
    ),
    SkillTemplate(
        key="intent-router-classify",
        label="意图路由 · 档位判定",
        description="判断需求复杂度并建议档位，只能降级。",
        category=JUDGMENT,
        prompt_template=intent_router.SYSTEM_PROMPT,
        role="intent_router",
        slot=intent_router.CLASSIFY_SLOT,
    ),
    SkillTemplate(
        key="intent-router-select-provider",
        label="意图路由 · 供应商选型",
        description="从已通过硬性能力过滤的候选里选出本次实际使用的供应商。",
        category=JUDGMENT,
        prompt_template=intent_router.SELECT_PROVIDER_SYSTEM_PROMPT,
        role="intent_router",
        slot=intent_router.SELECT_PROVIDER_SLOT,
    ),
    SkillTemplate(
        key="custom-judgment-default",
        label="自定义判断 · 中立结论",
        description="custom_agent 节点的内置兜底提示词，输出 verdict/confidence/notes。",
        category=JUDGMENT,
        prompt_template=custom.SYSTEM_PROMPT,
    ),
    SkillTemplate(
        key="judgment-classify",
        label="通用判断 · 内容分类",
        description="把输入归入一组自定义类别，需要先把类别列表填进模板占位处。",
        category=JUDGMENT,
        prompt_template=_GENERIC_CLASSIFY,
    ),
    SkillTemplate(
        key="judgment-score",
        label="通用判断 · 结构化评分",
        description="按相关性/完成度/新意三个维度打分并给出通过与否。",
        category=JUDGMENT,
        prompt_template=_GENERIC_SCORE,
    ),
    SkillTemplate(
        key="editor-planner-default",
        label="短剧剪辑规划 · 平台默认",
        description="根据规范化时间线摘要产出可执行 EditCommand，不发布、不改账本。",
        category=JUDGMENT,
        prompt_template=editor_planner.SYSTEM_PROMPT,
        tool_grants=("timeline_summary", "lookup_shortform_profile", "lookup_media_analysis"),
        role="editor_planner",
        slot=editor_planner.SLOT,
    ),
    SkillTemplate(
        key="canvas-planner-default",
        label="画布生成规划 · 平台默认",
        description="读取画布上选中卡片与其上游卡片，规划要生成的图片/视频任务。",
        category=JUDGMENT,
        prompt_template=canvas_planner.SYSTEM_PROMPT,
        # No tools: the planner is handed its whole context up front, and
        # pricing is computed server-side — see `AGENT_TOOL_GRANTS`.
        tool_grants=(),
        role="canvas_planner",
        slot=canvas_planner.CANVAS_PLAN_SLOT,
    ),
)


def templates_for(*, category: str | None = None, role: str | None = None) -> list[SkillTemplate]:
    """Templates an operator may load, most specific first.

    A role's own templates come before the category's generic ones so the
    dropdown opens on something written for exactly this agent.
    """
    matches = [
        template
        for template in SKILL_TEMPLATES
        if (category is None or template.category == category)
        and (role is None or template.role is None or template.role == role)
    ]
    matches.sort(key=lambda template: (template.role != role, template.key))
    return matches


def find(key: str) -> SkillTemplate | None:
    return next((template for template in SKILL_TEMPLATES if template.key == key), None)
