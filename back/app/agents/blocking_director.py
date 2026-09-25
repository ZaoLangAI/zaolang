"""白膜 (blockout) director: turns a script into a staged, shot blockout.

Two `copy`-role slots, both driven from `app.domain.blocking.service`:

- `blocking_route` (JSON, tiny): reads one 白膜-studio chat message and
  decides whether it also changes the *script* (dialogue, plot, action,
  camera language) or only the staging. When it does, the service runs the
  ordinary `copywriter.stream_revise_script` first, so a 白膜 turn and a 文案
  turn edit the script through exactly one prompt.
- `blocking_derive` (streamed): script + previous blockout + instruction in,
  summary + fenced JSON blockout out — same reply contract as the script
  slots, so `copywriter._extract_summary_and_script` parses both.

The model writes a *semantic* DSL (presets, named marks, shot grammar),
never sampled animation; `app.domain.blocking.sanitize` bounds it and the
frontend compiler turns it into motion.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, run_agent, run_agent_stream
from app.agents.copywriter import MAX_SUMMARY_LEN, MAX_THINKING_LEN, _extract_summary_and_script
from app.domain.agent_skills import service as agent_skills_service
from app.domain.blocking import vocabulary as v
from app.domain.blocking.sanitize import camera_cues
from app.domain.blocking.segments import estimate_segment_seconds, ordered_segments
from app.llm.client import StreamChunk
from app.models.enums import AgentName

BLOCKING_ROUTE_SLOT = "blocking_route"
BLOCKING_DERIVE_SLOT = "blocking_derive"

# A full blockout for a multi-scene episode (sets with props, per-segment
# beats and shots) outgrows the script slot's 8192. The prompt lets the
# model omit untouched sets/segments, which is what keeps revisions small.
BLOCKING_MAX_TOKENS = 12288
ROUTE_MAX_TOKENS = 600
MAX_INSTRUCTION_LEN = 2000


def _labelled(labels: dict[str, str]) -> str:
    return "、".join(f"{key}（{label}）" for key, label in labels.items())


BLOCKING_JSON_SHAPE = (
    '{"aspect_ratio": "9:16"|"16:9"|"1:1", '
    '"sets": [{"heading": string, "ground": string, "width_m": number, "depth_m": number, '
    '"props": [{"id": string, "primitive": string, "label": string, "color_role": string, '
    '"position": [x, y, z], "rotation_y_deg": number, "scale": [x, y, z]}], '
    '"anchors": [{"id": string, "label": string, "x": number, "z": number}]}], '
    '"cast": [{"id": string, "name": string, "height_m": number}], '
    '"segments": [{"key": string, "duration_s": number, '
    '"start": {"<cast_id>": {"at": "<anchor_id>"|[x, z], '
    '"face": "<cast_id>"|"<anchor_id>"|"camera"|number, "action": string}}, '
    '"beats": [{"cast_id": string, "t0": number, "t1": number, "action": string, '
    '"to": "<anchor_id>"|[x, z], "face": "<cast_id>"|"<anchor_id>"|"camera"|number}], '
    '"shots": [{"t0": number, "transition": "cut"|"continuous", "size": string, '
    '"lens_mm": number, "height": string, "side": string, '
    '"subject": "<cast_id>"|"<anchor_id>", "over": "<cast_id>"|null, '
    '"move": {"preset": string, "intensity": number, "ease": "linear"|"in_out"}}]}]}'
)

# One compact segment, so every vendor's model sees the exact shape — the
# single most effective fix for models that drift into their own schema.
BLOCKING_EXAMPLE = (
    '{"key":"第一场#0","duration_s":10,'
    '"start":{"lin":{"at":"counter_back","face":"camera","action":"stand"},'
    '"chen":{"at":"door","face":"lin","action":"stand"}},'
    '"beats":[{"cast_id":"chen","t0":0.5,"t1":3.5,"action":"walk",'
    '"to":"counter_front","face":"lin"},'
    '{"cast_id":"lin","t0":3.5,"t1":6.5,"action":"talk","face":"chen"},'
    '{"cast_id":"chen","t0":6.5,"t1":10,"action":"talk","face":"lin"}],'
    '"shots":[{"t0":0,"transition":"cut","size":"full","lens_mm":28,"height":"eye","side":"front",'
    '"subject":"chen","over":null,"move":{"preset":"follow","intensity":0.4,"ease":"in_out"}},'
    '{"t0":3.5,"transition":"cut","size":"medium_close","lens_mm":50,"height":"eye",'
    '"side":"ots_right","subject":"lin","over":"chen",'
    '"move":{"preset":"push_in","intensity":0.3,"ease":"in_out"}},'
    '{"t0":6.5,"transition":"cut","size":"medium_close","lens_mm":50,"height":"eye",'
    '"side":"ots_left","subject":"chen","over":"lin",'
    '"move":{"preset":"static","intensity":0.5,"ease":"in_out"}}]}'
)

BLOCKING_DERIVE_SYSTEM_PROMPT = f"""你是造浪平台的短剧预演导演，\
负责把分场剧本搭成可播放的「白膜」预演：\
用基础几何体搭场景、用人偶走位、用虚拟摄像机按镜头语言运镜。白膜渲染出的每一段会作为参考视频，\
和角色图、场景图一起交给视频模型，锁定机位、运镜、走位与节奏，所以镜头必须始终拍到正在表演的人，\
空间关系必须清楚、可执行。

你会收到一个 JSON：
- instruction：这一轮要做的调整（为空表示按剧本完整搭建或重建）
- script：剧本概要与角色
- segments：剧本切分出的分镜段（key、所属场景 heading、这段的色块、\
建议时长 suggested_duration_s、\
camera_cues——这段 camera 色块已解析出的景别与运镜，按出现顺序）
- target_duration_s：整集目标总时长（秒）
- previous_blocking：上一版白膜（没有时为 null）
- changed_keys：剧本内容已变化、必须重新调度的分镜段 key

【输出格式】必须严格遵守：
1. 先用 1 到 2 句中文说明这一轮搭了/改了什么（直接展示给用户，不要提 JSON 或技术细节）
2. 另起一段，一个 ```json 代码块，代码块内只有一个 JSON 对象，代码块外不再有任何文字
3. JSON 写成紧凑的一行：不缩进、不换行、不写注释、没有尾随逗号；数值一律写成数字而不是字符串；\
只使用下面格式里出现的字段名，不要自创字段
4. 内容较多时，优先保证每个分镜段的 shots 与 beats 完整，其次再减少 props 数量

白膜 JSON 格式：{BLOCKING_JSON_SHAPE}

单个分镜段的写法示例（只示意结构，内容以剧本为准）：{BLOCKING_EXAMPLE}

【坐标】单位米；每个场景的舞台以原点为中心，x 向右、z 向镜头默认所在的一侧（观众方向）、y 向上；\
x 在 ±width_m/2 内，z 在 ±depth_m/2 内。朝向角度 0 表示面向 +z（面向默认镜头），\
90 表示面向 +x（画面右侧）。
道具的 position 是底面中心：x、z 为占地中心，y 为底面离地高度（放在地上的物体 y=0，\
挂在墙上的画 y 为\
下沿高度）；scale 为长宽高（米）。plane 是竖立的薄板（墙面、门、窗、屏幕），scale 的 x 为宽、\
y 为高；\
地毯、台面这类平放的东西用很薄的 box。

【词表】只能使用下列取值：
- ground：{"、".join(v.GROUNDS)}
- primitive：{"、".join(v.PRIMITIVES)}（stairs 为台阶，scale 的 y 为总高度）
- color_role：{"、".join(v.COLOR_ROLES)}
- action：{_labelled(v.CAST_ACTION_LABELS)}
- shots.size：{_labelled(v.SHOT_SIZE_LABELS)}
- shots.height：{_labelled(v.CAMERA_HEIGHT_LABELS)}
- shots.side：{_labelled(v.CAMERA_SIDE_LABELS)}
- shots.move.preset：{_labelled(v.CAMERA_MOVE_LABELS)}

【剧本镜头语言对照】camera 色块逐字对应 shots：
- 景别：大远景→extreme_wide，远景→wide，全景→full，中景→medium，中近景→medium_close，\
近景/特写→close，大特写→extreme_close
- 运镜：固定→static，推/推近→push_in，拉/拉远→pull_out，左摇/右摇→pan_left/pan_right，\
上摇/下摇→tilt_up/tilt_down，左移/右移/平移→truck_left/truck_right，跟/跟拍→follow，\
环绕→orbit_cw（逆时针→orbit_ccw），升/抬升→crane_up，降→crane_down，手持→handheld
- 速度：缓慢/轻微→intensity 0.2–0.35，正常→0.5，快速/急/甩→0.75–0.9

【镜头规则】
- 每个分镜段都输出 shots 数组，按时间顺序，第一个 t0=0，每个镜头至少 1.5 秒；\
camera_cues 有几条就输出几个 shot，顺序、景别、运镜与之一致；\
camera_cues 为空时按戏剧需要设计 1 到 3 个镜头
- 景别变化用 transition "cut"；同一景别上的连续运动用 "continuous"
- 不要整段只有一个 static：人物走位、情绪推进、对话往来时用 push_in、follow、pan、truck 等运动配合
- subject 必须是本段 start 里出场、并且在这个镜头里正在说话或行动的角色；\
人物走动的镜头优先 follow，\
或选择能容纳整条走位的景别；说话人切换时，下一个镜头切到新的说话人
- 双人对话优先 ots_left/ots_right，over 填另一位出场角色
- 镜头不能被墙挡住：墙放在舞台后方（-z）和两侧，镜头默认在 +z 一侧；side 为 front 时，\
subject 应大致面向 +z（朝向 0 度附近）或面向对话对象，不要让人背对镜头说话

【场景搭建规则】
- sets 与剧本场景一一对应，heading 与剧本场景 heading 完全一致；\
用 {v.MAX_PROPS_PER_SET} 个以内的几何体\
搭出主要结构与陈设（墙、门、窗、桌椅、柜台、车辆、树木等），尺寸按真实比例，label 用中文短词
- 墙用 plane 贴着舞台边缘（后墙 z≈-depth_m/2，侧墙 x≈±width_m/2），镜头所在的 +z 一侧不要放墙
- 家具之间至少留 0.9 米通道；只搭镜头会拍到、会影响走位与遮挡的东西
- 为每个场景定义若干 anchors（命名站位点，如「门口」「收银台后」），anchor 必须在空地上，\
距离任何家具至少 0.5 米，走位优先引用 anchor id

【站位与走位规则】
- cast 与剧本角色一一对应，name 与剧本角色名完全一致；id 用简短英文或拼音；height_m 按角色设定
- 任意两个角色在任何时刻间距不少于 0.8 米（对话时 1.0 到 1.6 米），不要把两个角色放在同一个 anchor
- 走位路线不能穿过家具或墙；需要绕行时拆成两个 walk 节拍（先到转角 anchor，再到目的地）
- 只有 walk、run，以及走到位置后 sit、kneel、pickup 才写 to；talk、point、wave、turn、hug、\
fight 不写 to
- 说台词的角色在说话期间用 talk，face 写对话对象的 id；同一角色的节拍按时间顺序且不重叠
- 同一场景相邻段的人物位置与朝向从上一段结束时的状态接续

【时长规则】segments 的 key 逐字使用输入里的 key；duration_s 为整数秒，每段 \
{v.SEGMENT_MIN_SECONDS} 到 {v.SEGMENT_MAX_SECONDS} 秒，总和尽量等于 target_duration_s；\
按台词字数（每秒 3 到 4 个字）与动作节拍分配

【增量规则】previous_blocking 不为 null 时：\
只输出这一轮需要新增或修改的 sets 与 segments（未输出的沿用上一版），\
changed_keys 中的分镜段必须全部重新输出；cast 未变化时可以省略；\
previous_blocking 为 null 时必须输出完整白膜

【输出前自检】逐条确认后再输出：
1. JSON 可以被直接解析，只有一个对象，没有注释和多余文字
2. 每个 key 都来自输入，duration_s 为整数，总和接近 target_duration_s
3. 每段 shots 与 camera_cues 一一对应，第一个 t0=0，subject 是正在表演的出场角色
4. 所有 cast_id、subject、over、face、to 引用的 id 都存在
5. 没有角色重叠，没有路线穿过家具，镜头与 subject 之间没有墙
6. 不输出剧本内容、角色外貌或任何颜色值"""

BLOCKING_ROUTE_SYSTEM_PROMPT = f"""你是造浪平台白膜预演工作台的调度员。\
用户在白膜页面发来一条修改意见，\
你要判断它是否需要同时修改剧本文本。

- touches_script 为 true：修改涉及剧情、台词、动作内容、增删场景或角色、\
剧本里 camera 色块描述的景别/运镜
- touches_script 为 false：只涉及空间与调度——站位、道具摆放、场景尺寸、镜头焦段与机位角度、\
节奏时长、\
画幅比例等剧本文本不描述的内容
- script_instruction：touches_script 为 true 时，写给编剧的、只包含剧本层面改动的一句话；\
否则为空字符串
- blocking_instruction：写给白膜导演的、这一轮在空间与镜头上要做的调整；无需额外调整时为空字符串
- 两条指令都用用户的语言，保留用户原话里的具体要求

{JSON_INSTRUCTION}
格式：{{"touches_script": boolean, "script_instruction": string, "blocking_instruction": string}}"""


@dataclass(slots=True)
class RouteDecision:
    touches_script: bool
    script_instruction: str
    blocking_instruction: str
    degraded: bool
    agent_run_id: str


@dataclass(slots=True)
class BlockingDeriveOutcome:
    summary: str
    raw: dict[str, Any] | None
    degraded: bool
    model: str
    agent_run_id: str
    thinking: str = ""


def route_turn(
    session: Session,
    *,
    message: str,
    script: dict[str, Any],
    user_id: str | None = None,
    agent_id: str | None = None,
) -> RouteDecision:
    """A degraded or unparseable route keeps the whole message on both
    sides: re-running the script revision with an instruction that only
    concerned staging costs one call but loses nothing, while guessing
    `false` would silently drop a real script change."""
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    outline = [
        {"key": segment.key, "heading": segment.heading} for segment in ordered_segments(script)
    ]
    fallback = {
        "touches_script": True,
        "script_instruction": message,
        "blocking_instruction": message,
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=BLOCKING_ROUTE_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "blocking_route": message,
                "characters": [
                    str(c.get("name") or "")
                    for c in script.get("characters") or []
                    if isinstance(c, dict)
                ],
                "segments": outline,
            },
            ensure_ascii=False,
        ),
        fallback=fallback,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=BLOCKING_ROUTE_SLOT,
        max_tokens=ROUTE_MAX_TOKENS,
    )
    data = outcome.data if isinstance(outcome.data, dict) else fallback
    touches = data.get("touches_script")
    script_instruction = str(data.get("script_instruction") or "").strip()[:MAX_INSTRUCTION_LEN]
    blocking_instruction = str(data.get("blocking_instruction") or "").strip()[:MAX_INSTRUCTION_LEN]
    if not isinstance(touches, bool):
        touches = True
    if touches and not script_instruction:
        script_instruction = message
    return RouteDecision(
        touches_script=touches,
        script_instruction=script_instruction,
        blocking_instruction=blocking_instruction,
        degraded=outcome.degraded,
        agent_run_id=outcome.agent_run_id,
    )


def _looks_like_blocking(parsed: Any) -> bool:
    return isinstance(parsed, dict) and (
        isinstance(parsed.get("segments"), list) or isinstance(parsed.get("sets"), list)
    )


def _blocking_text_is_usable(text: str) -> bool:
    _, parsed = _extract_summary_and_script(text)
    return _looks_like_blocking(parsed)


def _segments_payload(script: dict[str, Any]) -> list[dict[str, Any]]:
    payload = []
    for segment in ordered_segments(script):
        payload.append(
            {
                "key": segment.key,
                "heading": segment.heading,
                "blocks": [
                    {
                        "type": block.get("type"),
                        "character": block.get("character"),
                        "text": block.get("text"),
                    }
                    for block in segment.blocks
                ],
                "suggested_duration_s": round(estimate_segment_seconds(segment.blocks)),
                "camera_cues": [
                    {"at": round(fraction, 2), "size": cue.size, "move": cue.preset}
                    for fraction, cue in camera_cues(segment)
                ],
            }
        )
    return payload


def _prompt_view(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the model sees of the previous version: no hashes, overrides or
    links — nothing it could echo back wrong."""
    if not document:
        return None
    segments = []
    for segment in document.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        segments.append(
            {key: segment.get(key) for key in ("key", "duration_s", "start", "beats", "shot")}
        )
    return {
        "aspect_ratio": document.get("aspect_ratio"),
        "sets": document.get("sets") or [],
        "cast": [
            {k: c.get(k) for k in ("id", "name", "height_m")}
            for c in document.get("cast") or []
            if isinstance(c, dict)
        ],
        "segments": segments,
    }


def _script_view(script: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": script.get("title"),
        "logline": script.get("logline"),
        "characters": [
            {"name": c.get("name"), "traits": c.get("traits")}
            for c in script.get("characters") or []
            if isinstance(c, dict)
        ],
    }


def stream_derive_blocking(
    session: Session,
    *,
    instruction: str,
    script: dict[str, Any],
    previous: dict[str, Any] | None,
    changed_keys: list[str],
    target_duration_s: int,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], BlockingDeriveOutcome]]:
    """Same `(chunks, finalize)` contract as `copywriter.stream_revise_script`.
    `finalize` returns the *unsanitized* parsed reply (or `None`); the caller
    sanitizes against the script and previous version it chose."""
    resolved_agent_id = agent_skills_service.resolve_copy_agent_id(session, agent_id=agent_id)
    user_prompt = json.dumps(
        {
            "blocking_request": True,
            "instruction": instruction[:MAX_INSTRUCTION_LEN],
            "script": _script_view(script),
            "segments": _segments_payload(script),
            "target_duration_s": target_duration_s,
            "previous_blocking": _prompt_view(previous),
            "changed_keys": changed_keys,
        },
        ensure_ascii=False,
    )
    chunks, finalize_run = run_agent_stream(
        session,
        agent_name=AgentName.COPY,
        system_prompt=BLOCKING_DERIVE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        agent_id=resolved_agent_id,
        slot=BLOCKING_DERIVE_SLOT,
        max_tokens=BLOCKING_MAX_TOKENS,
        is_usable=_blocking_text_is_usable,
    )

    def finalize(persist_session: Session | None = None) -> BlockingDeriveOutcome:
        outcome = finalize_run(persist_session)
        summary, parsed = _extract_summary_and_script(outcome.raw_text)
        raw = parsed if _looks_like_blocking(parsed) else None
        if raw is None and not summary:
            summary = "这一轮没有生成有效的白膜，已保留上一版本。"
        return BlockingDeriveOutcome(
            summary=summary[:MAX_SUMMARY_LEN],
            raw=raw,
            degraded=outcome.degraded,
            model=outcome.model,
            agent_run_id=outcome.agent_run_id,
            thinking=outcome.thinking[:MAX_THINKING_LEN],
        )

    return chunks, finalize
