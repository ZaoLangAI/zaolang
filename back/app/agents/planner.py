"""Planner agent: turns an intent into an executable generation plan."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.agents.slots import DEFAULT_SLOT
from app.models.enums import (
    AgentName,
    CharacterViewAngle,
    ImageAssetKind,
    Operation,
    QualityTier,
    VideoAssetKind,
)

SYSTEM_PROMPT = f"""你是造浪平台的创作规划器。根据用户意图与来源作品参数，产出一个可执行的生成计划。
规则：
- operation 只能是 text_to_image / text_to_video / image_to_video / video_to_video
- 若用户没有明确要求高质量，优先推荐 standard 档位以控制成本
- prompt_enhancements 是对原始描述的补充，不要改变用户的核心意图
- operation 为视频类时，prompt_enhancements 优先补充镜头/运镜、节奏与时长，不要只写氛围形容词
- negative_prompt_suggestions 是生成时需要规避的反面描述，用于降低常见失败率
  （例如复杂动作场景里的肢体/面部畸变、镜头抖动伪影），与本次意图无关时留空数组
- 涉及暴力、伤害等敏感画面时，prompt_enhancements 只补充镜头语言与氛围
  不要新增用户描述中没有出现的血腥、伤害细节——那类内容交给安全审核环节单独处理
- 不要编造用户没有提供的素材

{JSON_INSTRUCTION}
格式：{{"operation": string, "steps": [{{"name": string, "detail": string}}],
"recommended_tier": "preview"|"standard"|"cinematic", "prompt_enhancements": string[],
"negative_prompt_suggestions": string[]}}"""

FALLBACK: dict[str, Any] = {
    "operation": Operation.TEXT_TO_IMAGE.value,
    "steps": [{"name": "render", "detail": "按原始描述直接生成"}],
    "recommended_tier": QualityTier.STANDARD.value,
    "prompt_enhancements": [],
    "negative_prompt_suggestions": [],
}


def plan(
    session: Session,
    *,
    intent: str,
    source_params: dict[str, Any] | None = None,
    requested_operation: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    payload = {
        "intent": intent,
        "source_params": source_params or {},
        "requested_operation": requested_operation,
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=DEFAULT_SLOT,
    )

    # The user's explicit choice always wins over the model's suggestion.
    if requested_operation:
        outcome.data["operation"] = requested_operation
    if outcome.data.get("operation") not in {o.value for o in Operation}:
        outcome.data["operation"] = Operation.TEXT_TO_IMAGE.value
    if outcome.data.get("recommended_tier") not in {t.value for t in QualityTier}:
        outcome.data["recommended_tier"] = QualityTier.STANDARD.value
    enhancements = outcome.data.get("prompt_enhancements")
    outcome.data["prompt_enhancements"] = (
        [str(item)[:200] for item in enhancements[:8]] if isinstance(enhancements, list) else []
    )
    negatives = outcome.data.get("negative_prompt_suggestions")
    outcome.data["negative_prompt_suggestions"] = (
        [str(item)[:200] for item in negatives[:8]] if isinstance(negatives, list) else []
    )
    return outcome


CLARIFY_SLOT = "clarify"

QUESTION_KINDS = ("single_choice", "multi_choice", "free_text")
MAX_CLARIFY_QUESTIONS = 4
MAX_CLARIFY_OPTIONS = 6

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的创作规划顾问，在正式规划生成方案之前判断用户的意图描述
是否需要补充信息，才能规划出效果可靠的生成计划。
规则：
- 只有在缺少主体、场景、动作、镜头/构图、时长（视频时）这几类关键信息之一，
  且缺失会明显影响生成质量时才提问
- 描述已经具体、可以直接规划时，needs_clarification 为 false，questions 为空数组
- 每个问题只问一件事，问题数量不超过 {MAX_CLARIFY_QUESTIONS} 个，按对生成质量的影响从高到低排序
- kind 为 single_choice 或 multi_choice 时必须给 2 到 {MAX_CLARIFY_OPTIONS} 个
  具体、互斥或可组合的选项，不要给「其他」这类空泛选项
- kind 为 free_text 时 options 留空数组
- required 表示这个问题是否必须回答才能保证质量，不是强制用户必须点开
- 问题与选项用用户输入的语言书写

{JSON_INSTRUCTION}
格式：{{"needs_clarification": boolean, "questions": [{{"id": string,
"kind": "single_choice"|"multi_choice"|"free_text", "prompt": string,
"options": [{{"value": string, "label": string}}], "required": boolean}}]}}"""

CLARIFY_FALLBACK: dict[str, Any] = {"needs_clarification": False, "questions": []}


def clarify(
    session: Session,
    *,
    intent: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    job_id: str | None = None,
) -> AgentOutcome:
    """Judges whether an intent needs the author's input before planning.

    The fallback never blocks submission: a degraded or unparseable model
    call yields `needs_clarification=False`, so a gateway hiccup never
    becomes a dead end for the author (same reasoning as `copywriter.clarify`).
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({"intent": intent}, ensure_ascii=False),
        fallback=dict(CLARIFY_FALLBACK),
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=CLARIFY_SLOT,
    )
    questions = outcome.data.get("questions")
    outcome.data["questions"] = (
        [_sanitize_clarify_question(q) for q in questions[:MAX_CLARIFY_QUESTIONS]]
        if isinstance(questions, list)
        else []
    )
    outcome.data["questions"] = [q for q in outcome.data["questions"] if q is not None]
    outcome.data["needs_clarification"] = bool(outcome.data.get("needs_clarification")) and bool(
        outcome.data["questions"]
    )
    return outcome


def _sanitize_clarify_question(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind not in QUESTION_KINDS:
        return None
    question_id = str(raw.get("id") or "").strip()
    question_prompt = str(raw.get("prompt") or "").strip()
    if not question_id or not question_prompt:
        return None

    options: list[dict[str, str]] = []
    if kind in ("single_choice", "multi_choice"):
        raw_options = raw.get("options")
        if isinstance(raw_options, list):
            for option in raw_options[:MAX_CLARIFY_OPTIONS]:
                if not isinstance(option, dict):
                    continue
                value = str(option.get("value") or "").strip()
                label = str(option.get("label") or "").strip()
                if value and label:
                    options.append({"value": value[:64], "label": label[:64]})
        if not options:
            return None

    return {
        "id": question_id[:64],
        "kind": kind,
        "prompt": question_prompt[:200],
        "options": options,
        "required": bool(raw.get("required")),
    }


ASSET_PLAN_SLOT = "asset_plan"

_ASSET_KIND_BRIEF: dict[str, str] = {
    ImageAssetKind.CHARACTER.value: (
        "角色立绘：全身入镜（不裁切头脚），背景为单一纯色（不要自然场景/杂物），"
        "方便直接当参考图导入视频生成；清晰展示人物五官、发型、服装与体型，"
        "避免多人遮挡关键特征。具体是正面、侧面还是背面见 character_view。"
        "每次调用只生成 character_view 指定的这一个角度，输出必须是单一画面、"
        "单一视角的一张图，禁止在同一张图里拼接展示多个角度"
        "（例如把正面和侧面画在一起，或做成分格对比图/转身参考图）。"
    ),
    ImageAssetKind.SCENE.value: "短剧场景图：一个具体地点的空镜或建立镜头，无主要角色遮挡构图。",
    ImageAssetKind.COVER.value: (
        "短剧/系列封面：突出主视觉与氛围，适合竖版封面裁切，避免杂乱前景遮挡标题区。"
    ),
}

# Only consulted when `asset_kind == character` — the specific angle each of
# `GenerationParams.character_views`' entries asks for, one call at a time
# (see `app.workflows.nodes.execute_asset_planning`'s loop over them). All
# three keep the same full-body framing as `_ASSET_KIND_BRIEF` above — a
# front view cropped to half-body would leave the side/back completions
# with nothing consistent to match.
_CHARACTER_VIEW_BRIEF: dict[str, str] = {
    CharacterViewAngle.FRONT.value: ("正面视角：全身正面站姿，五官、发型、服装清晰可辨。"),
    CharacterViewAngle.SIDE.value: (
        "侧面视角：与正面同一人物的 90 度侧面全身站姿，姿态、服装与正面保持一致。"
    ),
    CharacterViewAngle.BACK.value: (
        "背面视角：与正面同一人物的背面全身站姿，发型/服装背面细节清晰。"
    ),
}

_ASSET_KIND_BRIEF_LINES = chr(10).join(f"- {k}: {v}" for k, v in _ASSET_KIND_BRIEF.items())
_CHARACTER_VIEW_BRIEF_LINES = chr(10).join(f"- {k}: {v}" for k, v in _CHARACTER_VIEW_BRIEF.items())

ASSET_PLAN_SYSTEM_PROMPT = f"""你是造浪平台的图片资产规划器，
负责把用户意图整理成适合特定用途的图片生成方案。
资产用途说明（asset_kind -> 要求）：
{_ASSET_KIND_BRIEF_LINES}
当 asset_kind 是 character 时，character_view 进一步说明这一张具体要哪个角度：
{_CHARACTER_VIEW_BRIEF_LINES}
规则：
- prompt_enhancements 只补充镜头、构图、光线、一致性相关的描述，不要改变用户描述的角色/场景本身特征
- 但当 asset_kind 是 character 时，全身入镜 + 单一纯色背景是硬性要求，优先级高于"不要改变
  用户描述本身特征"这条：如果用户描述里写了具体场景、环境或半身/中景/近景这类构图，
  prompt_enhancements 里也要明确加入"替换为纯色背景""改为全身入镜"这类描述去覆盖它们，
  背景与取景范围不算需要保留的"角色本身特征"
- 当 asset_kind 是 character 且用户之前已经生成过同一角色的其他视角时
  （source_params 里会带出该角色已有的描述），prompt_enhancements 必须包含足以保持发型、
  服装、体型一致的关键特征，不要遗漏
- subject_name 是这个角色/场景适合作为库内条目名称的简短命名（4-12 个字），
  没有更具体的名字时可以用一个概括性的称呼（例如"神秘女侦探"），但不要留空
- negative_prompt_suggestions 给出会破坏该用途可用性的反面描述
  （例如角色立绘要规避"多人入镜/半身裁切/复杂背景"）

{JSON_INSTRUCTION}
格式：{{"subject_name": string, "prompt_enhancements": string[],
"negative_prompt_suggestions": string[]}}"""

ASSET_PLAN_FALLBACK: dict[str, Any] = {
    "subject_name": "新角色",
    "prompt_enhancements": [],
    "negative_prompt_suggestions": [],
}


def plan_asset(
    session: Session,
    *,
    intent: str,
    asset_kind: str,
    character_view: str | None = None,
    target_character_id: str | None = None,
    target_scene_id: str | None = None,
    source_params: dict[str, Any] | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Plans a `text_to_image`/`image_to_image` job whose output is meant for
    the character/scene/cover library rather than a one-off image — see
    `app.workflows.nodes.execute_asset_planning`.

    `character_view` only matters when `asset_kind == "character"`: which of
    `front`/`side`/`back` this particular call's output is for, one call per
    entry in `GenerationParams.character_views` for a multi-view completion
    job (see `_CHARACTER_VIEW_BRIEF`).
    """
    payload = {
        "intent": intent,
        "asset_kind": asset_kind,
        "character_view": character_view,
        "target_character_id": target_character_id,
        "target_scene_id": target_scene_id,
        "source_params": source_params or {},
    }
    fallback = dict(ASSET_PLAN_FALLBACK)
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=ASSET_PLAN_SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=fallback,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=ASSET_PLAN_SLOT,
    )
    subject = outcome.data.get("subject_name")
    outcome.data["subject_name"] = str(subject).strip()[:60] if subject else "新角色"
    enhancements = outcome.data.get("prompt_enhancements")
    outcome.data["prompt_enhancements"] = (
        [str(item)[:200] for item in enhancements[:8]] if isinstance(enhancements, list) else []
    )
    negatives = outcome.data.get("negative_prompt_suggestions")
    outcome.data["negative_prompt_suggestions"] = (
        [str(item)[:200] for item in negatives[:8]] if isinstance(negatives, list) else []
    )
    return outcome


VIDEO_ASSET_PLAN_SLOT = "video_asset_plan"

# The video-side equivalent of `_ASSET_KIND_BRIEF`. A deliberately different
# judgment axis from the image briefs above: video guidance is about motion,
# camera movement and cut-friendly pacing, not composition/lighting for a
# single frame — see `VideoAssetKind`'s own docstring for why this is a
# fully separate system prompt rather than folded into `ASSET_PLAN_SYSTEM_PROMPT`.
_VIDEO_ASSET_KIND_BRIEF: dict[str, str] = {
    VideoAssetKind.SCENE.value: (
        "短剧场景空镜：设计一个具体地点的运镜方式（推/拉/摇/移/环绕），"
        "环境氛围与光线可以随镜头推进有变化，避免人物入镜打断场景的纯净度，"
        "给出适合剪辑对轨的清晰起幅与落幅动作。"
    ),
    VideoAssetKind.CHARACTER_ACTION.value: (
        "角色动作片段：设计一个具体、可执行的单一主体动作，动作的起幅与落幅要清晰，"
        "方便和其他镜头剪辑对轨；若 source_params 带出该角色已有的形象描述，"
        "动作设计必须保持与该形象一致（发型/服装/体型），避免复杂多人互动。"
    ),
    VideoAssetKind.TRANSITION.value: (
        "转场/运镜衔接片段：只设计纯运镜、光效或过渡元素，不包含明确的叙事内容，"
        "强调节奏感与可无缝拼接性，风格需要能承接前后正片镜头，不要突兀。"
    ),
    VideoAssetKind.COVER.value: (
        "短剧预告/封面视频：突出主视觉冲击与氛围，适合竖版预告裁切，"
        "节奏紧凑不拖沓，可以暗示剧情钩子但不要剧透关键转折。"
    ),
}

_VIDEO_ASSET_KIND_BRIEF_LINES = chr(10).join(
    f"- {k}: {v}" for k, v in _VIDEO_ASSET_KIND_BRIEF.items()
)

VIDEO_ASSET_PLAN_SYSTEM_PROMPT = f"""你是造浪平台的视频资产规划器，
负责把用户意图整理成适合特定用途的视频生成方案。
资产用途说明（video_asset_kind -> 要求）：
{_VIDEO_ASSET_KIND_BRIEF_LINES}
规则：
- prompt_enhancements 只补充镜头运镜、动作设计、节奏与时长相关的描述，
  不要改变用户描述的角色/场景/动作本身
- 当 video_asset_kind 是 character_action 且用户之前已经生成过该角色的形象时
  （source_params 里会带出该角色已有的描述），prompt_enhancements 必须包含足以保持
  发型、服装、体型一致的关键特征，不要遗漏
- subject_name 是这个角色/场景适合作为库内条目名称的简短命名（4-12 个字），
  没有更具体的名字时可以用一个概括性的称呼，但不要留空
- negative_prompt_suggestions 给出会破坏该用途可用性的反面描述
  （例如动作片段要规避"镜头抖动/肢体畸变/动作模糊不清"）

{JSON_INSTRUCTION}
格式：{{"subject_name": string, "prompt_enhancements": string[],
"negative_prompt_suggestions": string[]}}"""

VIDEO_ASSET_PLAN_FALLBACK: dict[str, Any] = {
    "subject_name": "新角色",
    "prompt_enhancements": [],
    "negative_prompt_suggestions": [],
}


def plan_video_asset(
    session: Session,
    *,
    intent: str,
    video_asset_kind: str,
    target_character_id: str | None = None,
    target_scene_id: str | None = None,
    source_params: dict[str, Any] | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Plans a `text_to_video`/`image_to_video`/`video_to_video` job whose
    output is meant for the scene/character-action/transition/cover clip
    library rather than a one-off video — the video-side equivalent of
    `plan_asset`, called from `app.workflows.nodes.execute_asset_planning`
    when `_asset_axis` resolves to `"video"`.

    Deliberately its own function/system-prompt (not `plan_asset` with a
    branch): video guidance is a different judgment axis (motion/camera
    movement/pacing vs. composition/lighting), and no video kind ever has a
    multi-view loop the way `character_view` does for images.
    """
    payload = {
        "intent": intent,
        "video_asset_kind": video_asset_kind,
        "target_character_id": target_character_id,
        "target_scene_id": target_scene_id,
        "source_params": source_params or {},
    }
    fallback = dict(VIDEO_ASSET_PLAN_FALLBACK)
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=VIDEO_ASSET_PLAN_SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=fallback,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=VIDEO_ASSET_PLAN_SLOT,
    )
    subject = outcome.data.get("subject_name")
    outcome.data["subject_name"] = str(subject).strip()[:60] if subject else "新角色"
    enhancements = outcome.data.get("prompt_enhancements")
    outcome.data["prompt_enhancements"] = (
        [str(item)[:200] for item in enhancements[:8]] if isinstance(enhancements, list) else []
    )
    negatives = outcome.data.get("negative_prompt_suggestions")
    outcome.data["negative_prompt_suggestions"] = (
        [str(item)[:200] for item in negatives[:8]] if isinstance(negatives, list) else []
    )
    return outcome
