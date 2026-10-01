"""Planner agent: turns an intent into an executable generation plan."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents import questions as agent_questions
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

# Re-exported from `app.agents.questions`, which owns the shape all three
# question-asking slots share (this one, the copy agent's own `clarify`, and
# the scene coach's polish-time follow-ups).
QUESTION_KINDS = agent_questions.QUESTION_KINDS
MAX_CLARIFY_QUESTIONS = agent_questions.MAX_QUESTIONS
MAX_CLARIFY_OPTIONS = agent_questions.MAX_OPTIONS

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的创作规划顾问，在正式规划生成方案之前判断用户的意图描述
是否需要补充信息，才能规划出效果可靠的生成计划。
规则：
- 只有在缺少主体、场景、动作、镜头/构图这几类关键信息之一，
  且缺失会明显影响生成质量时才提问
- 时长、分辨率、画面比例/画幅已经在提交创作时通过独立的表单控件必填，属于结构化参数，
  不是这段文字描述需要补充的信息：不要就这几项提问或建议调整，文字描述里没有出现
  秒数/分辨率/横竖屏/比例不代表缺失，不需要为此生成问题
- 当 has_reference_material 为 true 时（这是一次基于参考图片/参考视频的二次创作、续写或改编），
  画面主体、场景/背景外观已经由参考素材本身决定，不要就"主体是谁""背景/场景是什么"这类
  问题追问；只问参考素材回答不了的信息，例如具体想让参考素材发生的动作/剧情变化、
  想保留还是替换的部分、运镜或节奏要求
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
    has_reference_material: bool = False,
    user_id: str | None = None,
    agent_id: str | None = None,
    job_id: str | None = None,
) -> AgentOutcome:
    """Judges whether an intent needs the author's input before planning.

    The fallback never blocks submission: a degraded or unparseable model
    call yields `needs_clarification=False`, so a gateway hiccup never
    becomes a dead end for the author (same reasoning as `copywriter.clarify`).

    `has_reference_material` is true when this job already carries a
    reference image/video (remix source clip, attached still, first/last
    frame). The model must not then ask who/what the subject is or what
    the background looks like — the reference already answers that.
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.PLANNER,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {"intent": intent, "has_reference_material": has_reference_material},
            ensure_ascii=False,
        ),
        fallback=dict(CLARIFY_FALLBACK),
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=CLARIFY_SLOT,
    )
    outcome.data["questions"] = agent_questions.sanitize_questions(outcome.data.get("questions"))
    outcome.data["needs_clarification"] = bool(outcome.data.get("needs_clarification")) and bool(
        outcome.data["questions"]
    )
    return outcome


ASSET_PLAN_SLOT = "asset_plan"

_ASSET_KIND_BRIEF: dict[str, str] = {
    ImageAssetKind.CHARACTER.value: (
        "角色设定图：单张多分区输出（不要拆成多张），方便直接当参考图导入视频生成；"
        "清晰展示人物五官、发型、服装与体型，避免多人遮挡关键特征。"
        "人物性别、年龄段、肤色必须在画面中清晰可辨——"
        "这是角色识别的关键特征，不能省略或含糊。"
        "character_view=front 时按设定图版式出一张板；"
        "character_view=side/back 时仍只出那一个全身单视角（补全路径，禁止再拼一张设定图）。"
    ),
    ImageAssetKind.SCENE.value: (
        "短剧场景图：一个具体地点的纯静态空镜或建立镜头，主体是空间本身，"
        "画面中不能出现任何人物/角色痕迹（含背影、剪影、局部肢体或人群）。"
        "必须是单一机位、单一连续空间：门窗墙柱按真实房屋结构遮挡，"
        "关闭的门不得改成敞开以展示室内；禁止分割构图/分屏/同时画门内外两套空间。"
        "年代与地域（虚构场景则是世界观制式）和视觉媒介必须明确且全图一致，"
        "器物不得晚于所写年代，画面不得漂移成插画/3D 渲染/游戏截图。"
    ),
    ImageAssetKind.COVER.value: (
        "短剧/系列封面：突出主视觉与氛围，适合竖版封面裁切，避免杂乱前景遮挡标题区。"
    ),
}

# Only consulted when `asset_kind == character` — the specific angle each of
# `GenerationParams.character_views`' entries asks for, one call at a time
# (see `app.workflows.nodes.execute_asset_planning`'s loop over them).
# `front` is the library's character-sheet pass (one image, several panels);
# side/back stay single-view full-body so a leftover completion job does not
# emit a second sheet.
_CHARACTER_VIEW_BRIEF: dict[str, str] = {
    CharacterViewAngle.FRONT.value: (
        "设定图版式：单张、左右分栏。"
        "左侧从左到右全身三视图（正面、侧面、背面），站姿、不裁切头脚；"
        "右侧为面部多角度特写、服装面料与配饰细节、标准化色板；"
        "整板单一纯色/纯白背景，各分区为同一人物。"
    ),
    CharacterViewAngle.SIDE.value: (
        "侧面视角：与正面同一人物的 90 度侧面全身站姿，姿态、服装与正面保持一致。"
        "必须是单一画面、单一视角，禁止再做成设定图或分格拼贴。"
    ),
    CharacterViewAngle.BACK.value: (
        "背面视角：与正面同一人物的背面全身站姿，发型/服装背面细节清晰。"
        "必须是单一画面、单一视角，禁止再做成设定图或分格拼贴。"
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
- 但当 asset_kind 是 character 且 character_view 是 front（含未指定、默认 front）时，
  单张多分区设定图 + 整板单一纯色背景是硬性要求，优先级高于"不要改变用户描述本身特征"：
  如果用户只写了外貌、或写了具体场景/半身单视角，prompt_enhancements 必须补上
  "左右分栏设定图""左侧全身三视图""右侧特写与色板""替换为纯色背景"，
  不得把已有的设定图/三视图/色板收成一张全身正面立绘。背景与取景范围不算要保留的
  "角色本身特征"
- 当 asset_kind 是 character 且 character_view 是 side/back 时，单一视角全身 + 纯色背景
  仍是硬性要求：禁止再拼设定图或分格对比图，prompt_enhancements 不得加入三视图/色板版式
- 当 asset_kind 是 character 且用户之前已经生成过同一角色的其他视角时
  （source_params 里会带出该角色已有的描述），prompt_enhancements 必须包含足以保持发型、
  服装、体型一致的关键特征，不要遗漏
- 当 asset_kind 是 character 时，人物性别、年龄段、肤色必须在最终提示词里清晰、明确，
  这是硬性要求，优先级与设定图版式/纯色背景相同：如果用户描述（多来自剧本角色的外貌
  设定）没有清楚给出性别、年龄段或肤色中的任意一项，prompt_enhancements 必须补充合理且
  具体的描述去补全它，不是"用户没提到才补"的可选项，不能让角色图缺失这三项关键识别特征
- 当 asset_kind 是 character 时，视觉媒介同样是硬性要求：用户描述已写真人/写实/影视
  或动漫/二次元时必须原样保留，禁止改成另一种；都没写则 prompt_enhancements 必须补上
  「真人写实影视短剧造型」。negative_prompt_suggestions 必须排除对立媒介
  （写实排除「动漫/二次元/卡通/anime illustration」；动漫排除「真人照片/摄影棚写实」）
- 当 asset_kind 是 scene 时，无人物入镜同样是硬性要求，优先级高于"不要改变用户描述本身特征"
  这条：如果用户描述里写了人物或人物动作（哪怕只是带过一句），prompt_enhancements 里也要明确
  加入"去除人物""替换为无人纯场景"这类描述去覆盖它们，negative_prompt_suggestions 必须包含
  人物相关的反面描述（例如"人物/人影/背影/人群"）
- 当 asset_kind 是 scene 时，单一机位与房屋结构成立同样是硬性要求，优先级与无人物入镜相同：
  如果用户描述并列了门内外、或写了「或分割构图/或侧视」，prompt_enhancements 必须收成
  一个机位能看见的连续空间，并写明「关闭的遮挡保持关闭」「禁止分割构图」；
  不得把门打开以展示室内，也不得加入第二套同等机位。negative_prompt_suggestions 必须同时
  包含分割构图/分屏/门大开的全屋透视
- 当 asset_kind 是 scene 时，年代锚点与视觉媒介同样是硬性要求：真实场景的描述里没有
  年代或地域时，prompt_enhancements 必须补上具体的地域与年代，并落到能画出来的制式
  （门锁、开关面板、瓷砖、电表箱、灯具）；外太空/异星/赛博/末世/奇幻/水下这类虚构场景
  改为补世界观制式（技术等级、材质语言、重力与大气状态）。用户没写视觉媒介时必须补上
  「真人写实影视短剧实拍质感」，已写动漫/二次元则原样保留。negative_prompt_suggestions
  必须排除年代穿帮的现代物件与对立媒介（插画/3D 渲染/游戏截图/概念设定图）
- asset_pass 说明这一张具体是什么，优先级高于 character_view 的设定图规则：
  character_sheet = 角色设定图（按上面的设定图版式）；
  character_expressions = 表情合集图（source_params.character_expressions 列出各格表情）：
  只出同一人物的头肩特写宫格，禁止补三视图/设定图/色板/全身像，
  prompt_enhancements 只补充保持五官、发型、服装在各格一致的描述；
  scene = 单张场景图；scene_variant_group = 一组同一机位的场景变体
  （source_params.scene_variants 逐张列出光照/天气/状态/时期），每张独立成图，禁止拼接分格
- 当 source_params 带有 scene_lighting/scene_weather/scene_state/scene_period（或 scene_variants）
  时，这些预设已经写进了 intent，是硬性要求：prompt_enhancements 不得改写光照、天气、
  破损程度或年代，也不得引入与 scene_period 不同的年代器物；只补充与预设一致的细节
- 当 source_params.character_outfit_label 存在时，intent 描述的是该造型的服装，
  prompt_enhancements 不得改变人物五官与发型，只补充服装面料与配饰细节
- subject_name 是这个角色/场景适合作为库内条目名称的简短命名（4-12 个字），
  没有更具体的名字时可以用一个概括性的称呼（例如"神秘女侦探"），但不要留空
- negative_prompt_suggestions 给出会破坏该用途可用性的反面描述
  （front 设定图规避"多人入镜/故事场景/只出单一正面"；side/back 规避"分格拼贴/设定图版式"；
  scene 规避"人物/分割构图/分屏/门大开的全屋透视/年代穿帮的现代物件/插画/3D 渲染/游戏截图"）

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
    asset_pass: str | None = None,
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
    job (see `_CHARACTER_VIEW_BRIEF`). `asset_pass` is
    `prompt_builder.AssetPass` — what this pass actually produces (a sheet,
    a composite expression image, a scene variant group…); the builder has
    already composed its fixed text, the plan only adds to it.
    """
    payload = {
        "intent": intent,
        "asset_kind": asset_kind,
        "character_view": character_view,
        "asset_pass": asset_pass,
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
