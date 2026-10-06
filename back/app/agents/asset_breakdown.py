"""Breaks a script down into the asset cards it needs (剧本拆解, AC-9):
characters with appearance and age stage, scenes (one per place, with the
headings set there, its period and lighting) and props (with the headings
they appear in).

A `copy`-role helper with its own slot (agent-gateway invariant 14), the
same shape as `character_profile`. It only *proposes* —
`POST /v1/scripts/{id}:breakdown` returns the proposal and the author picks
新建 / 关联已有 / 忽略 per row before anything is written. The model's
output is bound to the script: a character must be one the script lists, a
scene's headings must exist, every preset must be in the closed vocabulary.
Whatever the model leaves out (or the whole proposal, on a degraded run) is
filled from the script itself, so the dialog always has every character and
every heading to decide on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, run_agent
from app.agents.copywriter import MAX_CHARACTERS, MAX_PROPS, MAX_SCENES, MAX_TITLE_LEN
from app.domain.agent_skills import service as agent_skills_service
from app.domain.image_assets.vocabulary import AGE_STAGES, SCENE_LIGHTINGS, SCENE_PERIODS
from app.models.enums import AgentName

ASSET_BREAKDOWN_SLOT = "asset_breakdown"

# Card descriptions are prompt seeds; `CharacterCreateRequest` allows more,
# but a breakdown line is one paragraph the author reviews in a dialog.
MAX_DESCRIPTION_LEN = 300
MAX_NAME_LEN = MAX_TITLE_LEN
# What the model reads per scene — the environment and action lines are
# what props and lighting are found in; dialogue rarely names an object.
MAX_SCENE_TEXT_LEN = 1200

BREAKDOWN_MAX_TOKENS = 4096
BREAKDOWN_TEMPERATURE = 0.3

SYSTEM_PROMPT = f"""你是造浪平台的短剧美术统筹。你会收到一部分场剧本：标题、梗概、\
角色表（name + traits），以及每一场的 heading 和这场的环境、动作、台词文字。

把剧本拆成需要建卡的三类资产，只写剧本能支撑的内容，不编造剧本里没有的人和物：

1. characters——角色表里的每一个角色各一条：
- name 必须和角色表里的写法一字不差
- appearance：用于反复生成这个角色的定妆照。先写全剧统一的视觉媒介\
（默认「真人写实影视短剧造型」），再写性别、年龄段、肤色、发型发色、体型、标志性穿着或配饰；只写稳定的静态外貌，\
不写表情、姿态、性格和经历；{MAX_DESCRIPTION_LEN} 字以内
- age_stage：只能取 {" / ".join(AGE_STAGES)} 之一（child 儿童、teen 少年、youth 青年、\
adult 成年、middle_aged 中年、elderly 老年），剧本看不出就填 null

2. scenes——按地点拆，不按场次：同一个地点的多场戏合成一条，headings 列出发生在这里的所有 heading：
- name：地点名，不带场次、日夜和内外，例如「便利店」「顾家书房」；20 字以内
- headings：必须和收到的 heading 一字不差，每个 heading 只能归到一个地点
- description：只写空间本身——建筑结构、陈设、材质、色调，用于生成没有人物的主场景图；\
不能出现人物和动作；{MAX_DESCRIPTION_LEN} 字以内
- period：只能取 {" / ".join(SCENE_PERIODS)} 之一（ancient 古代、republic 民国、1980s、1990s、\
contemporary 当代、near_future 近未来），看不出填 null
- lighting：这个地点最主要的光线，只能取 {" / ".join(SCENE_LIGHTINGS)} 之一，看不出填 null

3. props——推动剧情或被角色拿在手里、需要在多个镜头里保持一致的物件（信物、凶器、合同、\
手机里的照片……）；家具、墙面这类场景陈设不算道具，最多 {MAX_PROPS} 个：
- name：物件名，例如「碎玉佩」；20 字以内
- description：外观——材质、颜色、尺寸、新旧和损坏状态，用于生成道具主视图；\
{MAX_DESCRIPTION_LEN} 字以内
- headings：这个物件出现的场次，必须和收到的 heading 一字不差

{JSON_INSTRUCTION}
格式：{{"characters": [{{"name": "...", "appearance": "...", "age_stage": "adult"}}], \
"scenes": [{{"name": "...", "headings": ["..."], "description": "...", "period": null, \
"lighting": "night_interior"}}], \
"props": [{{"name": "...", "description": "...", "headings": ["..."]}}]}}"""


@dataclass(frozen=True, slots=True)
class CharacterProposal:
    name: str
    appearance: str
    age_stage: str | None


@dataclass(frozen=True, slots=True)
class SceneProposal:
    name: str
    headings: tuple[str, ...]
    description: str
    period: str | None
    lighting: str | None


@dataclass(frozen=True, slots=True)
class PropProposal:
    name: str
    description: str
    headings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Breakdown:
    characters: list[CharacterProposal] = field(default_factory=list)
    scenes: list[SceneProposal] = field(default_factory=list)
    props: list[PropProposal] = field(default_factory=list)
    # The model gave nothing usable; everything above came from the script.
    degraded: bool = False


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _choice(value: Any, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _scene_text(scene: dict[str, Any]) -> str:
    lines = []
    for block in scene.get("blocks") or []:
        if not isinstance(block, dict) or block.get("type") == "breakpoint":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        speaker = block.get("character")
        lines.append(f"{speaker}：{text}" if block.get("type") == "dialogue" and speaker else text)
    return "\n".join(lines)[:MAX_SCENE_TEXT_LEN]


def _environment_text(scene: dict[str, Any]) -> str:
    texts = [
        str(block.get("text") or "").strip()
        for block in scene.get("blocks") or []
        if isinstance(block, dict) and block.get("type") == "scene"
    ]
    return "，".join(text for text in texts if text)[:MAX_DESCRIPTION_LEN]


# 「第一场 · 便利店 - 夜」→「便利店」: the scene number, day/night and
# interior/exterior marks are not part of a place's name.
_SCENE_NUMBER = re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇两]+\s*[场幕集]\s*")
_HEADING_SPLIT = re.compile(r"\s*[·•|/／\-—–－,，、]\s*|\s+")
_TIME_MARKS = frozenset(
    {"日", "夜", "晨", "清晨", "早", "早晨", "午", "中午", "下午", "傍晚", "黄昏", "深夜",
     "凌晨", "白天", "夜晚", "内", "外", "日内", "日外", "夜内", "夜外", "内景", "外景",
     "INT", "EXT", "INT.", "EXT.", "DAY", "NIGHT"}
)  # fmt: skip


def place_name(heading: str) -> str:
    """The place a scene heading names — the fallback scene card name."""
    rest = _SCENE_NUMBER.sub("", heading.strip())
    for token in _HEADING_SPLIT.split(rest):
        token = token.strip("（）() ")
        if token and token.upper() not in _TIME_MARKS and token not in _TIME_MARKS:
            return token[:MAX_NAME_LEN]
    return heading.strip()[:MAX_NAME_LEN]


def _baseline(script: dict[str, Any]) -> tuple[list[CharacterProposal], list[SceneProposal]]:
    characters = [
        CharacterProposal(
            name=_clean(item.get("name"), MAX_NAME_LEN),
            appearance=_clean(item.get("traits"), MAX_DESCRIPTION_LEN),
            age_stage=None,
        )
        for item in script.get("characters") or []
        if isinstance(item, dict) and _clean(item.get("name"), MAX_NAME_LEN)
    ]
    scenes = [
        SceneProposal(
            name=place_name(str(scene.get("heading"))),
            headings=(str(scene.get("heading")),),
            description=_environment_text(scene),
            period=None,
            lighting=None,
        )
        for scene in script.get("scenes") or []
        if isinstance(scene, dict) and str(scene.get("heading") or "").strip()
    ]
    return characters, scenes


def sanitize(raw: Any, script: dict[str, Any]) -> Breakdown:
    """Binds the model's proposal to `script` and fills the gaps from it.

    Characters keep the script's order and names; a scene's headings are
    filtered to the script's own, each heading belongs to the first place
    that claims it, and headings no place claimed become a place of their
    own (`place_name`). Scenes with the same name merge. Props are capped
    at `MAX_PROPS`, one per name.
    """
    data = raw if isinstance(raw, dict) else {}
    baseline_characters, baseline_scenes = _baseline(script)
    script_headings = [heading for scene in baseline_scenes for heading in scene.headings]
    heading_set = set(script_headings)

    proposed: dict[str, dict[str, Any]] = {}
    for item in _list(data.get("characters")):
        if isinstance(item, dict):
            name = _clean(item.get("name"), MAX_NAME_LEN)
            if name and name not in proposed:
                proposed[name] = item
    characters = []
    for base in baseline_characters[:MAX_CHARACTERS]:
        item = proposed.get(base.name) or {}
        characters.append(
            CharacterProposal(
                name=base.name,
                appearance=_clean(item.get("appearance"), MAX_DESCRIPTION_LEN) or base.appearance,
                age_stage=_choice(item.get("age_stage"), AGE_STAGES),
            )
        )

    places: dict[str, dict[str, Any]] = {}
    claimed: set[str] = set()
    for item in _list(data.get("scenes")):
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), MAX_NAME_LEN)
        raw_headings = _list(item.get("headings"))
        headings = [
            str(heading)
            for heading in raw_headings
            if str(heading) in heading_set and str(heading) not in claimed
        ]
        if not name or not headings:
            continue
        claimed.update(headings)
        place = places.setdefault(
            name,
            {
                "headings": [],
                "description": _clean(item.get("description"), MAX_DESCRIPTION_LEN),
                "period": _choice(item.get("period"), SCENE_PERIODS),
                "lighting": _choice(item.get("lighting"), SCENE_LIGHTINGS),
            },
        )
        place["headings"].extend(headings)
    for base_scene in baseline_scenes:
        heading = base_scene.headings[0]
        if heading in claimed:
            continue
        claimed.add(heading)
        place = places.setdefault(
            base_scene.name,
            {
                "headings": [],
                "description": base_scene.description,
                "period": None,
                "lighting": None,
            },
        )
        place["headings"].append(heading)
    order = {heading: index for index, heading in enumerate(script_headings)}
    scenes = [
        SceneProposal(
            name=name,
            headings=tuple(sorted(place["headings"], key=order.__getitem__)),
            description=place["description"],
            period=place["period"],
            lighting=place["lighting"],
        )
        for name, place in places.items()
    ]
    scenes.sort(key=lambda scene: order[scene.headings[0]])

    props: list[PropProposal] = []
    seen: set[str] = set()
    for item in _list(data.get("props")):
        if len(props) >= MAX_PROPS:
            break
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), MAX_NAME_LEN)
        if not name or name in seen:
            continue
        seen.add(name)
        raw_headings = _list(item.get("headings"))
        prop_headings = tuple(
            sorted(
                {str(heading) for heading in raw_headings if str(heading) in heading_set},
                key=order.__getitem__,
            )
        )
        props.append(
            PropProposal(
                name=name,
                description=_clean(item.get("description"), MAX_DESCRIPTION_LEN),
                headings=prop_headings,
            )
        )
    return Breakdown(characters=characters, scenes=scenes[:MAX_SCENES], props=props)


def breakdown(session: Session, *, script: dict[str, Any], user_id: str | None = None) -> Breakdown:
    """Proposes the cards `script` (an episode's `script_json`) needs.

    Never raises for a bad model run: a degraded run returns the script's
    own characters and places with `degraded=True` and no props, so the
    author can still link or create cards by hand.
    """
    payload = {
        "asset_breakdown": True,
        "title": _clean(script.get("title"), MAX_TITLE_LEN),
        "logline": _clean(script.get("logline"), MAX_DESCRIPTION_LEN),
        "characters": [
            {"name": item.get("name"), "traits": item.get("traits") or ""}
            for item in script.get("characters") or []
            if isinstance(item, dict)
        ][:MAX_CHARACTERS],
        "scenes": [
            {"heading": scene.get("heading"), "text": _scene_text(scene)}
            for scene in script.get("scenes") or []
            if isinstance(scene, dict)
        ][:MAX_SCENES],
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback={"characters": [], "scenes": [], "props": []},
        user_id=user_id,
        agent_id=agent_skills_service.resolve_copy_agent_id(session),
        slot=ASSET_BREAKDOWN_SLOT,
        max_tokens=BREAKDOWN_MAX_TOKENS,
        temperature=BREAKDOWN_TEMPERATURE,
    )
    if outcome.degraded:
        base = sanitize({}, script)
        return Breakdown(characters=base.characters, scenes=base.scenes, degraded=True)
    return sanitize(outcome.data, script)
