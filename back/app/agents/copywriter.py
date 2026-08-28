"""Copy agent: suggests a title, description and tags for a draft."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent, run_agent_stream
from app.domain.agent_skills import service as agent_skills_service
from app.llm.client import StreamChunk
from app.llm.normalize import extract_json, strip_thinking
from app.models import AgentRun
from app.models.enums import AgentName, AgentRunStatus
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

# Two unrelated system prompts share the `copy` agent identity, so each names
# its own slot — see `app.agents.slots`.
SUGGEST_SLOT = "suggest"
ENHANCE_SLOT = "enhance"

SYSTEM_PROMPT = f"""你是造浪平台的文案助手。为即将发布的作品生成标题、简介与标签。
规则：
- 标题不超过 24 个字，具体而有画面感，不使用「震撼」「绝美」这类空洞形容词
- 简介 1 到 2 句，说明画面内容与创作手法
- 标签 3 到 6 个，使用小写英文，用连字符连接多词标签
- 输出语言与用户输入保持一致

{JSON_INSTRUCTION}
格式：{{"title": string, "description": string, "tags": string[]}}"""

FALLBACK: dict[str, Any] = {
    "title": "未命名作品",
    "description": "",
    "tags": [],
}


def suggest(
    session: Session,
    *,
    prompt: str,
    lineage_summary: str = "",
    locale: str = "zh-CN",
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {"prompt": prompt, "lineage": lineage_summary, "locale": locale},
            ensure_ascii=False,
        ),
        fallback=FALLBACK,
        user_id=user_id,
        agent_id=agent_id,
        slot=SUGGEST_SLOT,
    )

    title = str(outcome.data.get("title") or FALLBACK["title"])
    outcome.data["title"] = title[:200]
    tags = outcome.data.get("tags")
    outcome.data["tags"] = [str(t)[:64] for t in tags][:6] if isinstance(tags, list) else []
    return outcome


DETAIL_LEVELS = ("sparse", "adequate", "detailed")

# What the coach diagnoses, per medium. A video prompt lives or dies on motion
# and camera work; a still one on composition and material detail. Asking for
# all of them regardless would put "运镜舒缓" on a poster and "构图对称" on a
# tracking shot, which is how generic advice starts.
VIDEO_DIMENSIONS = ("subject", "scene", "action", "camera", "lighting", "mood", "pacing")
IMAGE_DIMENSIONS = ("subject", "scene", "composition", "lighting", "style", "detail")
DIMENSION_KEYS = tuple(dict.fromkeys(VIDEO_DIMENSIONS + IMAGE_DIMENSIONS))
DIMENSION_STATUSES = ("missing", "weak", "ok")

# Bounds on everything the model hands back. The panel renders these verbatim,
# so an over-long hint is a layout bug rather than a richer answer.
MAX_DIMENSIONS = 8
MAX_DIMENSION_HINT_LENGTH = 60
MAX_ADDITIONS = 6
MAX_ADDITION_LENGTH = 40
MAX_FEEDBACK_LENGTH = 300

# One round's requested adjustment. Free-text `instruction` covers everything
# else; these exist so the panel can offer one-tap directions and so the test
# fake gateway (`tests/fake_llm_gateway.py`) can mirror them deterministically.
ENHANCE_DIRECTIONS = (
    "more_specific",
    "more_concise",
    "stronger_camera",
    "stronger_lighting",
    "more_dramatic",
)

VIDEO_OPERATIONS_FOR_ENHANCE = ("text_to_video", "image_to_video", "video_to_video")

# A diagnosis plus a hint per dimension plus the rewrite runs well past the
# generic 2048-token fallback, and a JSON reply cut off mid-object costs a
# second round trip to recover (`client._attempt_endpoint`). This is a slot
# *request*; the serving endpoint's `max_output_tokens` / `context_length`
# still cap it at call time.
ENHANCE_MAX_TOKENS = 4096
# Higher than the platform default of 0.2, which exists to keep verdicts and
# routing decisions repeatable. This slot rewrites prose: at 0.2 every polish
# reaches for the same handful of stock phrases.
ENHANCE_TEMPERATURE = 0.7

ENHANCE_SYSTEM_PROMPT = f"""你是造浪平台的提示词教练。用户正在写一段用于 AI 生成的画面描述，\
你要先逐维度诊断它缺什么，再改写它，并且让用户看完就知道下次该怎么自己写。

你会收到一个 JSON，字段含义：
- prompt：用户当前的画面描述
- operation：本次生成类型，{"/".join(VIDEO_OPERATIONS_FOR_ENHANCE)} 是视频，\
text_to_image/image_to_image 是图片
- aspect_ratio、duration_seconds、quality_tier：画幅、时长（秒）、质量档位，可能为空
- style_hint：用户已经套用的风格或技能，可能为空
- has_reference：用户是否已经上传参考图或参考视频
- direction、instruction：用户这一轮要求的调整方向与自由补充要求，可能为空
- max_length：润色后文本的字数上限

第一步，逐维度诊断。视频看 subject 主体、scene 场景、action 动作、camera 镜头、\
lighting 光线、mood 氛围、pacing 节奏；图片看 subject 主体、scene 场景、composition 构图、\
lighting 光线、style 风格、detail 细节。只输出与本次 operation 对应的那一组维度。
每个维度给一个 status：
- missing：描述里完全没有提到
- weak：提到了但太笼统，模型只能自由发挥
- ok：已经具体到可以直接拿去生成
每个维度配一句 hint，不超过 {MAX_DIMENSION_HINT_LENGTH} 个字：missing 或 weak 时\
说清楚要补什么、并给一个可以直接照抄的具体例子；ok 时用一句话说明它具体在哪里。\
hint 是给用户看的教学，不是给模型的指令。

第二步，由诊断结果决定 detail_level：有两个及以上 missing 是 sparse；\
没有 missing 但有 weak 是 adequate；全部 ok 是 detailed。

第三步，改写 prompt：
- 保留用户的核心意图与关键元素，不要换成另一个故事
- 只补 missing 与 weak 的维度，ok 的维度原样保留；\
补充幅度与诊断匹配，sparse 补得多，detailed 只做措辞打磨
- 每一处补充都要是模型能画出来的东西，不写「震撼」「绝美」「氛围感拉满」这类没有画面信息的形容词
- has_reference 为 true 时不要重复描述参考素材里已有的外貌细节，把笔墨放在动作与镜头上
- 视频要写清楚镜头怎么动、动作怎么推进；图片不要写运镜和时间推进
- duration_seconds 很短时不要塞进多个镜头或多段情节
- 不超过 max_length 个字

第四步，把这一轮真正加进去的短语列进 additions，最多 {MAX_ADDITIONS} 条、\
每条不超过 {MAX_ADDITION_LENGTH} 个字，用于给用户高亮这次补了什么；没有实质补充时给空数组。

direction 不为空时，这一轮只沿该方向调整，不要推翻上一轮已经补好的内容：
- more_specific：把还笼统的地方写得更具体
- more_concise：在不丢关键信息的前提下压缩长度
- stronger_camera：强化镜头语言，景别、运镜、视角
- stronger_lighting：强化光线、色调与明暗关系
- more_dramatic：强化戏剧张力与情绪对比
instruction 不为空时优先满足 instruction，它比 direction 更具体。

feedback 是给用户看的一两句总评，说这段描述当前最值得改的是什么，语气是教练不是评委。
feedback、hint、prompt、additions 全部使用 prompt 本身的语言书写。

{JSON_INSTRUCTION}
格式：{{"detail_level": "sparse"|"adequate"|"detailed", "feedback": string, "prompt": string, \
"dimensions": [{{"key": string, "status": "missing"|"weak"|"ok", "hint": string}}], \
"additions": string[]}}"""

# Asset-kind-specific variants of `ENHANCE_SYSTEM_PROMPT`, one per bucket in
# `agent_skills.service.ASSET_KIND_BUCKETS`. Each keeps every rule above
# verbatim and only appends what that image kind's job actually needs judged
# on — a character card lives or dies on face/outfit consistency across
# turnarounds, a scene asset on environment and atmosphere, a cover on
# whatever reads at thumbnail size. Used two ways: as the seed data these
# kinds' dedicated `AgentProfile`s publish (`app.scripts.seed`), and as the
# code-level fallback `enhance_prompt` passes to `run_agent` when no profile
# has been seeded/published yet — see `resolve_prompt`'s fallback order.
ENHANCE_SYSTEM_PROMPT_CHARACTER = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是角色资产 asset_kind=character）：
- 额外看一个隐含维度：人物一致性——发色、瞳色、发型、体型、标志性服饰/配饰是否写得足够具体，\
足以支撑后续正面/侧面/背面三视图长得像同一个人
- 表情与神态要给出具体描述（例如嘴角弧度、眼神方向），不要只写情绪词
- 不要引入会让三视图冲突的细节，例如只在这一轮出现的临时姿势或道具
- 硬性要求，不是"用户没提到才补"的可选项：画面必须全身入镜（不裁切头脚）、背景必须是\
单一纯色（不要任何场景、环境、地面纹理或散落物）——这样才能直接当参考图导入视频生成。\
即使用户描述里写了具体场景、环境细节或半身/中景/近景这类景别，改写后的 prompt 也要把\
背景替换成单一纯色、把景别改成全身，不能保留会和这条要求冲突的场景描述；这不算改变角色\
本身的特征——人物的外貌、服装、姿态、表情这些才是要保留的"本身特征"，背景与取景范围不算
- feedback 里如果人物一致性维度弱，要点名指出"这些细节要在多张图里保持一致"；如果原描述\
写了会冲突的场景或景别，也要点一句"已替换为全身 + 纯色背景，方便导入视频\""""

ENHANCE_SYSTEM_PROMPT_SCENE = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是场景资产 asset_kind=scene）：
- 额外看一个隐含维度：环境细节——建筑/地貌结构、时间与天气、空间尺度是否写得足够具体
- 氛围要落在光影、色调、天气这类可画出来的线索上，不要只写"氛围感强"之类的空词
- 硬性要求，不是"用户没提到才补"的可选项：画面中不能出现任何人物/角色（包括背影、剪影、\
局部肢体或人群等任何形式的人物痕迹），场景图必须是纯静态的空镜或建立镜头，主体是空间本身，\
不需要参演角色。即使用户描述里写了具体人物或人物动作，改写后的 prompt 也要把人物相关描述\
去掉，只保留环境、光影、氛围等场景要素
- feedback 里如果环境细节维度弱，要点名指出场景里哪个具体元素（建筑/植被/光源等）需要写清楚；\
如果原描述包含人物，也要提醒一句"已去除人物描写，仅保留纯场景\""""

ENHANCE_SYSTEM_PROMPT_COVER = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是封面资产 asset_kind=cover）：
- 额外看一个隐含维度：视觉焦点——画面主视觉是否单一且突出，避免多个同等重要的主体互相抢注意力
- 提醒画面上下左右预留可放标题文字的安全区，构图不要把主视觉铺满整个画幅
- 色彩与明暗对比要足够强，缩略图尺寸下依然能一眼看清主视觉
- feedback 里如果视觉焦点维度弱，要点名指出当前描述里谁在跟主视觉抢焦点"""

_ENHANCE_SYSTEM_PROMPTS: dict[str, str] = {
    "character": ENHANCE_SYSTEM_PROMPT_CHARACTER,
    "scene": ENHANCE_SYSTEM_PROMPT_SCENE,
    "cover": ENHANCE_SYSTEM_PROMPT_COVER,
}

# Video-side equivalents, one per non-`GENERAL` `VideoAssetKind`. Kept in a
# separate dict from `_ENHANCE_SYSTEM_PROMPTS` above — even though the two
# never collide by key (`VideoAssetKind`'s values are spelled distinctly,
# `character_action`/... — see its docstring) — so it stays explicit in the
# code that this is the video-language table, not something that could
# silently pick up an image-worded prompt for a video job.
ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是角色动作片段 video_asset_kind=character_action）：
- 额外看一个隐含维度：动作可执行性——动作的起幅与落幅是否写清楚，是否是单一主体可以\
实际完成的具体动作，不要写抽象的情绪化描述（如"霸气登场"）
- has_reference 为 true 时不要重复描述角色外貌，把笔墨放在动作细节与镜头跟随方式上
- 不要引入需要多人协同、容易在生成中出现肢体穿模的复杂互动动作
- feedback 里如果动作可执行性维度弱，要点名指出动作的起止节点需要写得更具体"""

ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是转场/运镜衔接片段 video_asset_kind=transition_video）：
- 额外看一个隐含维度：节奏与可拼接性——是否写清楚了纯运镜/光效/过渡元素，\
而不是带有明确叙事内容的镜头
- 不要引入具体角色或场景的叙事描述，这类片段的作用是衔接前后正片镜头，不是讲故事
- feedback 里如果节奏与可拼接性维度弱，要点名指出当前描述里哪部分更像正片叙事而非转场"""

ENHANCE_SYSTEM_PROMPT_COVER_VIDEO = f"""{ENHANCE_SYSTEM_PROMPT}

补充规则（本次是预告/封面视频 video_asset_kind=cover_video）：
- 额外看一个隐含维度：视觉冲击与节奏——开场 1-2 秒是否有足够抓人的画面，\
节奏是否紧凑不拖沓
- 提醒可以暗示剧情钩子但不要写出会剧透关键转折的具体情节
- feedback 里如果视觉冲击与节奏维度弱，要点名指出当前描述哪里显得平淡或拖沓"""

_VIDEO_ENHANCE_SYSTEM_PROMPTS: dict[str, str] = {
    "character_action": ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION,
    "transition_video": ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO,
    "cover_video": ENHANCE_SYSTEM_PROMPT_COVER_VIDEO,
}


def enhance_prompt(
    session: Session,
    *,
    prompt: str,
    max_length: int,
    operation: str = "",
    aspect_ratio: str = "",
    duration_seconds: int | None = None,
    quality_tier: str = "",
    style_hint: str = "",
    has_reference: bool = False,
    direction: str = "",
    instruction: str = "",
    asset_kind: str = "",
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Diagnoses a scene description dimension by dimension, then rewrites it.

    The generation context is passed through rather than left to the model's
    imagination: the same sentence needs different advice at 4 seconds than at
    15, and camera direction is noise on a still image.

    `asset_kind` is the job's `ImageAssetKind` (`character`/`scene`/`cover`/
    `general`) or `VideoAssetKind` (`character_action`/
    `transition_video`/`cover_video`/`general`) value, whichever axis is
    active — empty for an audio polish, and the two never collide (see
    `VideoAssetKind`'s docstring). When it names one of the asset buckets
    (`agent_skills.service.ASSET_KIND_BUCKETS`, spanning both axes) and the
    caller has not pinned an `agent_id` itself, this routes to that bucket's
    dedicated default agent — see `agent_skills.service
    .default_profile_for_asset_kind` — and always uses that bucket's
    specialised system prompt (image: `_ENHANCE_SYSTEM_PROMPTS`; video:
    `_VIDEO_ENHANCE_SYSTEM_PROMPTS`) as the code-level fallback, so the extra
    diagnostic rules apply even before an operator has published a matching
    `AgentSkill`.

    The fallback keeps the caller's own text rather than a static placeholder,
    so a degraded model call never empties the field it was meant to improve.
    Callers still have to treat `outcome.degraded` as a failure — the echoed
    text is not a polish (see `app.domain.prompts.enhance`).
    """
    resolved_agent_id = agent_id
    if resolved_agent_id is None and asset_kind in agent_skills_service.ASSET_KIND_BUCKETS:
        specific = agent_skills_service.default_profile_for_asset_kind(
            session, agent_skills_service.ASSET_KIND_AGENT_ROLE, asset_kind
        )
        if specific is not None:
            resolved_agent_id = specific.id
    enhance_system_prompt = (
        _ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or _VIDEO_ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or ENHANCE_SYSTEM_PROMPT
    )
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=enhance_system_prompt,
        user_prompt=_enhance_user_prompt(
            prompt=prompt,
            operation=operation,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            quality_tier=quality_tier,
            style_hint=style_hint,
            has_reference=has_reference,
            direction=direction,
            instruction=instruction,
            max_length=max_length,
        ),
        fallback={"prompt": prompt, "detail_level": "adequate", "feedback": ""},
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=ENHANCE_SLOT,
        max_tokens=ENHANCE_MAX_TOKENS,
        temperature=ENHANCE_TEMPERATURE,
    )
    return _sanitize_enhance_outcome(outcome, prompt=prompt, max_length=max_length)


def stream_enhance_prompt(
    session: Session,
    *,
    prompt: str,
    max_length: int,
    operation: str = "",
    aspect_ratio: str = "",
    duration_seconds: int | None = None,
    quality_tier: str = "",
    style_hint: str = "",
    has_reference: bool = False,
    direction: str = "",
    instruction: str = "",
    asset_kind: str = "",
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], AgentOutcome]]:
    """HTTP-SSE counterpart to `enhance_prompt`."""
    resolved_agent_id = agent_id
    if resolved_agent_id is None and asset_kind in agent_skills_service.ASSET_KIND_BUCKETS:
        specific = agent_skills_service.default_profile_for_asset_kind(
            session, agent_skills_service.ASSET_KIND_AGENT_ROLE, asset_kind
        )
        if specific is not None:
            resolved_agent_id = specific.id
    enhance_system_prompt = (
        _ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or _VIDEO_ENHANCE_SYSTEM_PROMPTS.get(asset_kind)
        or ENHANCE_SYSTEM_PROMPT
    )
    user_prompt = _enhance_user_prompt(
        prompt=prompt,
        operation=operation,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        quality_tier=quality_tier,
        style_hint=style_hint,
        has_reference=has_reference,
        direction=direction,
        instruction=instruction,
        max_length=max_length,
    )
    fallback = {"prompt": prompt, "detail_level": "adequate", "feedback": ""}
    chunks, finalize = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=enhance_system_prompt,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=ENHANCE_SLOT,
        max_tokens=ENHANCE_MAX_TOKENS,
        temperature=ENHANCE_TEMPERATURE,
        expect_json=True,
        is_usable=_enhance_text_is_usable,
    )

    def finish(persist_session: Session | None = None) -> AgentOutcome:
        stream = finalize(persist_session)
        parsed = extract_json(strip_thinking(stream.raw_text))
        parse_failed = parsed is None
        if parse_failed:
            _mark_enhance_run_failed(persist_session, stream.agent_run_id)
        data = dict(parsed) if parsed is not None else dict(fallback)
        outcome = AgentOutcome(
            data=data,
            raw_text=stream.raw_text,
            degraded=parse_failed or stream.degraded,
            model=stream.model,
            agent_run_id=stream.agent_run_id,
            thinking=stream.thinking,
        )
        return _sanitize_enhance_outcome(outcome, prompt=prompt, max_length=max_length)

    return chunks, finish


def _enhance_text_is_usable(text: str) -> bool:
    """`is_usable` gate for a recovered reasoning-only polish pass.

    Same contract as `_script_text_is_usable`: thinking prose that never
    resolves into a JSON object must trigger one budget expansion, not be
    handed back as a successful `result.text`.
    """
    return extract_json(strip_thinking(text)) is not None


def _mark_enhance_run_failed(session: Session | None, agent_run_id: str) -> None:
    """`run_agent_stream` records success before the caller parses JSON."""
    if session is None:
        return
    run = session.get(AgentRun, agent_run_id)
    if run is None:
        return
    run.degraded = True
    run.degrade_reason = "json_parse_failed"
    run.status = AgentRunStatus.FAILED


def _enhance_user_prompt(
    *,
    prompt: str,
    operation: str,
    aspect_ratio: str,
    duration_seconds: int | None,
    quality_tier: str,
    style_hint: str,
    has_reference: bool,
    direction: str,
    instruction: str,
    max_length: int,
) -> str:
    return json.dumps(
        {
            "prompt": prompt,
            "operation": operation,
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration_seconds,
            "quality_tier": quality_tier,
            "style_hint": style_hint,
            "has_reference": has_reference,
            "direction": direction,
            "instruction": instruction,
            "max_length": max_length,
        },
        ensure_ascii=False,
    )


def _sanitize_enhance_outcome(
    outcome: AgentOutcome, *, prompt: str, max_length: int
) -> AgentOutcome:
    enhanced = str(outcome.data.get("prompt") or "").strip() or prompt
    outcome.data["prompt"] = enhanced[:max_length]
    detail_level = str(outcome.data.get("detail_level") or "adequate")
    outcome.data["detail_level"] = detail_level if detail_level in DETAIL_LEVELS else "adequate"
    outcome.data["feedback"] = str(outcome.data.get("feedback") or "")[:MAX_FEEDBACK_LENGTH]
    outcome.data["dimensions"] = _sanitize_dimensions(outcome.data.get("dimensions"))
    outcome.data["additions"] = _sanitize_additions(outcome.data.get("additions"))
    return outcome


def _sanitize_dimensions(raw: Any) -> list[dict[str, str]]:
    """Keeps only known `(key, status)` pairs, first occurrence wins.

    An unknown key would reach the panel as an untranslated label, and a
    duplicate would render the same row twice — both are worse than dropping
    whatever the model improvised.
    """
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    dimensions: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        status = str(item.get("status") or "").strip()
        if key not in DIMENSION_KEYS or status not in DIMENSION_STATUSES or key in seen:
            continue
        seen.add(key)
        dimensions.append(
            {
                "key": key,
                "status": status,
                "hint": str(item.get("hint") or "").strip()[:MAX_DIMENSION_HINT_LENGTH],
            }
        )
        if len(dimensions) == MAX_DIMENSIONS:
            break
    return dimensions


def _sanitize_additions(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    additions: list[str] = []
    for item in raw:
        text = str(item).strip()[:MAX_ADDITION_LENGTH]
        if text:
            additions.append(text)
        if len(additions) == MAX_ADDITIONS:
            break
    return additions


CLARIFY_SLOT = "clarify"

QUESTION_KINDS = ("single_choice", "multi_choice", "free_text")
MAX_CLARIFY_QUESTIONS = 4
MAX_CLARIFY_OPTIONS = 6

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的短剧创作顾问，
在用户提交生成请求之前判断这段画面描述是否需要补充信息。
规则：
- 只有在缺少主体、场景、动作、镜头这几类关键信息之一，且缺失会明显影响生成质量时才提问
- 描述已经具体、可以直接生成时，needs_clarification 为 false，questions 为空数组
- 每个问题只问一件事，问题数量不超过 {MAX_CLARIFY_QUESTIONS} 个，按对生成质量的影响从高到低排序
- kind 为 single_choice 或 multi_choice 时必须给 2 到 {MAX_CLARIFY_OPTIONS} 个具体、互斥或可组合的
  选项，不要给「其他」这类空泛选项
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
    prompt: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Judges whether a scene description needs the author's input before generating.

    The fallback never blocks submission: a degraded or unparseable model call
    yields `needs_clarification=False`, so a gateway hiccup never becomes a
    dead end for the author.
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt}, ensure_ascii=False),
        fallback=dict(CLARIFY_FALLBACK),
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


# --- Script writing (剧本创作) -----------------------------------------
#
# Unlike `suggest`/`enhance`/`clarify` above, these two slots stream and do
# not return one JSON blob: the model is asked for a short prose summary
# (shown as the chat bubble) followed by a fenced ```json block holding the
# *entire* script document (not a diff). `run_agent_stream` has no notion of
# `fallback`/JSON-mode, so extraction and validation of the fenced block
# happens here, once the stream is fully drained.

SCRIPT_DRAFT_SLOT = "script_draft"
SCRIPT_REVISE_SLOT = "script_revise"

# A full scene-by-scene script (summary + fenced JSON for several scenes,
# each with several color blocks) routinely runs past the generic 2048
# fallback, the same reasoning `ENHANCE_MAX_TOKENS` documents for a much
# smaller payload. This is a slot *request*, not a hard ceiling: the serving
# endpoint's own `max_output_tokens`/`context_length` still cap it
# (`LlmProviderEndpoint.output_budget`), and a reasoning model's *first*
# attempt is still this slot request, not the endpoint's entire declared
# ceiling — only a truncated/unusable first pass expands the budget from
# here (see `_stream_complete_from_endpoints`'s retry, gated by
# `_script_text_is_usable` below).
SCRIPT_MAX_TOKENS = 8192

SCRIPT_JSON_SHAPE = (
    '{"title": string, "logline": string, '
    '"characters": [{"name": string, "traits": string}], '
    '"scenes": [{"heading": string, "blocks": '
    '[{"type": "scene"|"action"|"camera"|"dialogue"|"breakpoint", '
    '"character": string|null, "text": string}]}]}'
)

# Shared between the draft and revise prompts so a color block's meaning
# never drifts between a script's first turn and a later revision turn.
# `scene`'s "no people, ever" rule exists because this exact text is what
# `script-document-view.tsx::sceneImagePrompt` seeds the "生成场景图" jump-out
# with verbatim — a scene block that mixes in a character produces a seed
# prompt the scene-asset pipeline (`planner._ASSET_KIND_BRIEF[SCENE]`) then
# has to strip back out, so it's cheaper to never write it in the first place.
_BLOCK_TYPE_RULES = """- type 含义与写法：
  - scene：纯静态环境/氛围描述，只写空间本身——建筑或地貌结构、光线、色调、天气、陈设；\
不能出现任何人物（含背影、剪影、局部肢体或人群痕迹）、动作或对话内容。这段文字会被直接当作\
生成场景图的素材使用，混入人物或动作会导致场景图跑出不该出现的角色
  - action：一个色块只写一个连续的动作节拍（有清楚起止的一个动作），不要把多个动作或场景切换\
揉进同一个色块；落在具体的身体动作、手势、表情细节上，不写"情绪爆发""气氛紧张"这类模型画不出来\
的空词
  - camera：写出具体的景别（远景/全景/中景/近景/特写）+运镜方式（推/拉/摇/移/跟/升降/固定/甩镜）\
组合，例如「中景固定转特写推镜」，不要只写"镜头缓缓移动"这类模糊描述
  - dialogue：character 字段填说话人姓名，其余类型 character 为 null
  - breakpoint：建议的生成/剪辑切分点，不是场景内容本身
- 每一场戏必须包含至少一个 scene 色块，为这场戏保留一段可以直接拿去生成场景图的干净环境描述；\
scene 色块之外，同一场戏还要至少覆盖 action、dialogue 两类中的一类
- 拆分粒度：同一时间点内不同的动作、镜头切换、对话轮次都要拆成独立色块，不要为了减少色块数量把\
几件事挤进同一句话里——细粒度色块是为了让后续可以逐镜头生成与剪辑"""

# `characters[].traits` is what `script-document-view.tsx::characterImagePrompt`
# seeds the "生成角色图" jump-out with verbatim (no separate appearance field —
# this is the one and only place a character's visual gets described), so
# it must lead with what a character portrait actually needs — appearance —
# rather than personality, which a text-to-image model has no way to render.
_CHARACTER_APPEARANCE_RULE = """- characters 至少列出剧本中出现的主要角色，每个角色的 traits \
必须先写外貌特征——性别、年龄段、肤色、发型/发色、体型、面部或标志性穿着等，写到足以直接支撑\
角色立绘/角色图生成的程度，这部分不能省略、不能含糊；外貌之后再补充性格、人物关系等信息。\
例如「年轻女性，二十出头，肤色偏白，齐肩黑发，穿便利店店员制服；外冷内热，藏着不能说的秘密」\
而不是只写「外冷内热的便利店店员」"""

# A single generation call can never produce more than this many seconds of
# footage (`app.platform_config.schemas.MAX_GENERATION_DURATION_SECONDS`) —
# read live so an admin lowering the platform ceiling is reflected the next
# time a script is drafted/revised, without touching this prompt text.
_BREAKPOINT_RULES = f"""- breakpoint 是建议的切分点，不是场景内容本身：character 始终为 null，\
text 用一句话说明为什么在这里切，例如「建议在此处切分：前段约 18 秒台词与动作，\
符合单条生成 ≤{MAX_GENERATION_DURATION_SECONDS} 秒上限」
- 默默给每个 scene、action、camera、dialogue 色块估算大致时长（对话按语速，动作按镜头节奏），\
一旦某个场景内连续未切分的内容累计将超过 {MAX_GENERATION_DURATION_SECONDS} 秒，\
就在其后插入一个 breakpoint 色块，把这个场景拆成可以分别生成、分别剪辑的若干段
- breakpoint 优先落在自然的戏剧节拍上（一次反转、一次反应镜头、一次转场），\
不要卡在一句台词中间
- 很短的场景可以完全不需要 breakpoint；不要为了切分而切分"""

SCRIPT_DRAFT_SYSTEM_PROMPT = f"""你是造浪平台的短剧编剧助手，深度理解竖屏短剧的叙事节奏\
与生成流水线的限制。根据用户给出的创意，直接产出一份可用于拍摄/生成的完整分场短剧剧本。

输出严格分两部分，按顺序：
第一部分：用 1 到 2 句话说明你生成了什么，这句话会直接展示给用户，不要提到 JSON 或任何技术细节。
第二部分：另起一段，用一个 ```json 代码块输出完整剧本，\
代码块内只有一个 JSON 对象，代码块外和代码块内都不要有其他文字。

剧本 JSON 格式：{SCRIPT_JSON_SHAPE}

规则：
{_BLOCK_TYPE_RULES}
- 剧本至少包含 1 到 3 个场景
{_CHARACTER_APPEARANCE_RULE}
- 短剧节奏要快：第一场的第一个色块必须已经在建立冲突、悬念或反差，不能用寒暄或环境铺垫开场
- 每一场戏都要有一个明确的钩子或转折收尾，让人想看下一场——不要写成平铺直叙的流水账
- 每个镜头默认只安排一到两个正在说话/行动的角色，人物关系与画面在竖屏窄画幅里也能看清楚
- 台词要短、口语化、有潜台词，避免书面语和大段解释性独白；一句台词说不清楚就拆成前后两句；\
避免连续多轮台词都是长句陈述，适当加入打断、反问、沉默停顿，让对话有真实节奏
{_BREAKPOINT_RULES}
- 如果用户提供了参考技能的风格说明，把其中的调性、氛围、叙事手法融入剧本，但不要直接照抄技能描述原文
- 输出语言与用户输入保持一致"""

SCRIPT_REVISE_SYSTEM_PROMPT = f"""你是造浪平台的短剧编剧助手，正在和用户反复打磨一份剧本，\
同样需要兼顾竖屏短剧的叙事节奏与生成流水线的限制。\
你会收到当前剧本的完整内容和用户这一轮的修改意见，产出修改后的完整剧本。

输出严格分两部分，按顺序：
第一部分：用 1 到 2 句话说明这一轮改了什么，这句话会直接展示给用户，不要提到 JSON 或任何技术细节。
第二部分：另起一段，用一个 ```json 代码块输出修改后的完整剧本（是完整剧本，不是增量或补丁），\
代码块内只有一个 JSON 对象，代码块外和代码块内都不要有其他文字。

剧本 JSON 格式与当前剧本一致：{SCRIPT_JSON_SHAPE}

规则：
{_BLOCK_TYPE_RULES}
{_CHARACTER_APPEARANCE_RULE}
- 只按用户这一轮的意见调整，其余场景、角色、台词尽量原样保留，不要做用户没有要求的改写\
（包括已有角色的 traits——用户没有要求修改角色外貌/性格时原样保留，不要顺手补全或改写外貌描述）
- 用户没有要求删除的场景或角色不要删除
- 调整或新增内容后，重新检查一遍受影响场景的 breakpoint 是否仍然合理：\
新增的内容让某段超过 {MAX_GENERATION_DURATION_SECONDS} 秒时补插 breakpoint，\
删减后某个 breakpoint 不再必要时可以去掉，其余未受影响的 breakpoint 原样保留
{_BREAKPOINT_RULES}
- 如果用户提供了参考技能的风格说明，把其中的调性、氛围、叙事手法融入这一轮修改
- 输出语言与用户输入保持一致"""

SCRIPT_BLOCK_TYPES = ("scene", "action", "camera", "dialogue", "breakpoint")
MAX_SCENES = 40
MAX_BLOCKS_PER_SCENE = 60
MAX_CHARACTERS = 20
MAX_TEXT_LEN = 400
MAX_TITLE_LEN = 60
MAX_TRAITS_LEN = 300
MAX_HEADING_LEN = 80
MAX_SUMMARY_LEN = 300
# The reasoning trace persisted per turn (`EpisodeScriptTurn.thinking_text`)
# can run far longer than the visible summary/text fields above — a
# thinking model narrating its plan easily runs into the thousands of
# characters — so this gets a floor of its own rather than reusing
# `MAX_TEXT_LEN`/`MAX_SUMMARY_LEN`.
MAX_THINKING_LEN = 8000

_SCRIPT_JSON_FENCE = re.compile(r"```json\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass(slots=True)
class ScriptTurnOutcome:
    summary: str
    script: dict[str, Any]
    parse_ok: bool
    degraded: bool
    model: str
    agent_run_id: str
    thinking: str = ""


def _extract_summary_and_script(raw_text: str) -> tuple[str, Any]:
    """Splits the streamed reply into its prose summary and fenced JSON body.

    Returns `(summary, parsed_or_none)` — `parsed_or_none` is whatever
    `json.loads` produced (not yet validated as a script shape) or `None`
    when no fenced block was found or it didn't parse.

    Falls back to `extract_json` (balanced-brace scanning, not just a fence
    match) when there is no ```json fence at all — a model that ignores the
    "always fence it" instruction and just emits bare JSON after its summary
    must not be treated as if it produced no script.
    """
    match = _SCRIPT_JSON_FENCE.search(raw_text)
    if not match:
        parsed = extract_json(raw_text)
        if parsed is None:
            return raw_text.strip(), None
        # `extract_json` finds the JSON wherever it starts, so whatever
        # precedes it is the prose summary — same trade-off the fenced path
        # makes below.
        prefix = raw_text[: raw_text.find("{")].strip()
        return prefix or raw_text.strip(), parsed
    summary = raw_text[: match.start()].strip()
    try:
        parsed = json.loads(match.group(1))
    except (TypeError, ValueError):
        return summary or raw_text.strip(), None
    return summary or raw_text.strip(), parsed


def _script_text_is_usable(text: str) -> bool:
    """`is_usable` gate passed to `run_agent_stream`/`stream_complete`.

    A pass recovered from reasoning-only output (the glm-5.3-flash case) is
    only worth accepting when a script can actually be found in it — plain
    "thinking out loud" prose that never reaches a JSON payload must not be
    handed back as a successful `result.text` (see `stream_complete`'s
    `is_usable` docstring for exactly when this gate fires: never once real
    `content` has streamed, only on a recovered pass).
    """
    _, parsed = _extract_summary_and_script(text)
    return _sanitize_script(parsed) is not None


def _sanitize_script(raw: Any) -> dict[str, Any] | None:
    """Validates and bounds a model-produced script document.

    Returns `None` when nothing usable survives (no scenes at all) so the
    caller can fall back to the previous version rather than overwrite it
    with an empty document.
    """
    if not isinstance(raw, dict):
        return None

    title = str(raw.get("title") or "").strip()[:MAX_TITLE_LEN]
    logline = str(raw.get("logline") or "").strip()[:MAX_TEXT_LEN]

    characters: list[dict[str, Any]] = []
    raw_characters = raw.get("characters")
    if isinstance(raw_characters, list):
        for item in raw_characters[:MAX_CHARACTERS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:MAX_TITLE_LEN]
            if not name:
                continue
            traits = str(item.get("traits") or "").strip()[:MAX_TRAITS_LEN]
            # The model never sets this itself (it isn't told the field
            # exists) — only present when sanitizing a client-supplied
            # `current_script` that already carries a link. See
            # `_carry_over_links` for how a link survives a model turn that
            # doesn't echo it back.
            ref = item.get("character_ref_id")
            characters.append(
                {"name": name, "traits": traits, "character_ref_id": str(ref) if ref else None}
            )

    scenes: list[dict[str, Any]] = []
    raw_scenes = raw.get("scenes")
    if isinstance(raw_scenes, list):
        for scene in raw_scenes[:MAX_SCENES]:
            if not isinstance(scene, dict):
                continue
            heading = str(scene.get("heading") or "").strip()[:MAX_HEADING_LEN]
            if not heading:
                continue
            blocks: list[dict[str, Any]] = []
            raw_blocks = scene.get("blocks")
            if isinstance(raw_blocks, list):
                for block in raw_blocks[:MAX_BLOCKS_PER_SCENE]:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "")
                    if block_type not in SCRIPT_BLOCK_TYPES:
                        continue
                    text = str(block.get("text") or "").strip()[:MAX_TEXT_LEN]
                    if not text:
                        continue
                    character = block.get("character")
                    character_name = str(character).strip()[:MAX_TITLE_LEN] if character else None
                    blocks.append({"type": block_type, "character": character_name, "text": text})
            if blocks:
                ref = scene.get("ref_id")
                scenes.append(
                    {"heading": heading, "blocks": blocks, "ref_id": str(ref) if ref else None}
                )

    if not scenes:
        return None
    return {"title": title, "logline": logline, "characters": characters, "scenes": scenes}


def _carry_over_links(previous: dict[str, Any], updated: dict[str, Any]) -> None:
    """Re-attaches `character_ref_id`/`ref_id` links from the pre-turn script
    onto the post-turn one, matched by name/heading.

    A revision turn always returns the *entire* document (invariant #16 in
    `zaolang-editor-drama`), but the model is never told these link fields
    exist, so its own JSON output naturally omits them — without this, every
    single revision turn would silently unlink every character/scene the
    user had already connected to a reusable asset. Matching by name/heading
    rather than position is the same trade-off `PATCH .../links` makes: if
    the model renames something in the same turn, that one link is dropped
    rather than mismatched onto the wrong character/scene.
    """
    character_refs = {
        str(item.get("name")): item.get("character_ref_id")
        for item in previous.get("characters") or []
        if isinstance(item, dict) and item.get("character_ref_id")
    }
    for item in updated.get("characters") or []:
        if isinstance(item, dict) and not item.get("character_ref_id"):
            ref = character_refs.get(str(item.get("name")))
            if ref:
                item["character_ref_id"] = ref

    scene_refs = {
        str(scene.get("heading")): scene.get("ref_id")
        for scene in previous.get("scenes") or []
        if isinstance(scene, dict) and scene.get("ref_id")
    }
    for scene in updated.get("scenes") or []:
        if isinstance(scene, dict) and not scene.get("ref_id"):
            ref = scene_refs.get(str(scene.get("heading")))
            if ref:
                scene["ref_id"] = ref


def stream_draft_script(
    session: Session,
    *,
    idea: str,
    title: str = "",
    referenced_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], ScriptTurnOutcome]]:
    """Streams the first turn of a new script: idea in, full script out.

    Mirrors `run_agent_stream`'s `(chunks, finalize)` contract — the caller
    must drain `chunks` before calling `finalize()`.
    """
    user_prompt = json.dumps(
        {"idea": idea, "title": title, "referenced_skills": referenced_skills or []},
        ensure_ascii=False,
    )
    chunks, finalize_run = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SCRIPT_DRAFT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=agent_id,
        slot=SCRIPT_DRAFT_SLOT,
        max_tokens=SCRIPT_MAX_TOKENS,
        is_usable=_script_text_is_usable,
    )

    def finalize(persist_session: Session | None = None) -> ScriptTurnOutcome:
        outcome = finalize_run(persist_session)
        summary, parsed = _extract_summary_and_script(outcome.raw_text)
        script = _sanitize_script(parsed)
        parse_ok = script is not None
        if script is None:
            script = {
                "title": (title or idea).strip()[:MAX_TITLE_LEN],
                "logline": idea.strip()[:MAX_TEXT_LEN],
                "characters": [],
                "scenes": [],
            }
            if not summary:
                summary = "剧本生成失败，请换一种方式描述你的创意后重试。"
        return ScriptTurnOutcome(
            summary=summary[:MAX_SUMMARY_LEN],
            script=script,
            parse_ok=parse_ok,
            degraded=outcome.degraded,
            model=outcome.model,
            agent_run_id=outcome.agent_run_id,
            thinking=outcome.thinking[:MAX_THINKING_LEN],
        )

    return chunks, finalize


def stream_revise_script(
    session: Session,
    *,
    message: str,
    current_script: dict[str, Any],
    referenced_skills: list[dict[str, str]] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], ScriptTurnOutcome]]:
    """Streams one revision turn: current script + instruction in, full
    updated script out. The fallback on parse failure is the caller's own
    `current_script`, unchanged — a degraded turn must never blank out a
    document the user has already built up over several turns."""
    user_prompt = json.dumps(
        {
            "message": message,
            "current_script": current_script,
            "referenced_skills": referenced_skills or [],
        },
        ensure_ascii=False,
    )
    chunks, finalize_run = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SCRIPT_REVISE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=agent_id,
        slot=SCRIPT_REVISE_SLOT,
        max_tokens=SCRIPT_MAX_TOKENS,
        is_usable=_script_text_is_usable,
    )

    def finalize(persist_session: Session | None = None) -> ScriptTurnOutcome:
        outcome = finalize_run(persist_session)
        summary, parsed = _extract_summary_and_script(outcome.raw_text)
        script = _sanitize_script(parsed)
        parse_ok = script is not None
        if script is None:
            script = current_script
            if not summary:
                summary = "本轮修改未生成有效剧本，已保留上一版本，请换个方式描述修改意见。"
        else:
            _carry_over_links(current_script, script)
        return ScriptTurnOutcome(
            summary=summary[:MAX_SUMMARY_LEN],
            script=script,
            parse_ok=parse_ok,
            degraded=outcome.degraded,
            model=outcome.model,
            agent_run_id=outcome.agent_run_id,
            thinking=outcome.thinking[:MAX_THINKING_LEN],
        )

    return chunks, finalize
