"""Drafts a library character's description and voice description from the
scripts that use it (`app.domain.characters.script_context`).

A `copy`-role helper with its own slot (agent-gateway invariant 14), the
same shape as `skill_matcher`. It only *proposes*: the caller returns the
text to the author, who edits it before anything is saved — so a degraded
run raises instead of echoing the input back as if it were a draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, run_agent
from app.agents.copywriter import _CHARACTER_APPEARANCE_RULE
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ProviderTemporaryFailure
from app.models.enums import AgentName

CHARACTER_DESCRIBE_SLOT = "character_describe"
VOICE_MATCH_SLOT = "voice_match"

# `CharacterCreateRequest` limits: the draft must save as-is.
MAX_DESCRIPTION_LEN = 2000
MAX_VOICE_DESCRIPTION_LEN = 500
# What the model sees per script and in total — a long series must not
# crowd the instructions out of the context.
MAX_SCRIPTS_IN_PROMPT = 6
MAX_LINES_PER_SCRIPT = 20

DESCRIBE_MAX_TOKENS = 1200
DESCRIBE_TEMPERATURE = 0.4

DESCRIBE_FIELDS = ("description", "voice_description")

SYSTEM_PROMPT = f"""你是造浪平台的角色设定编辑。你会收到一个角色库角色的名称、\
作者已写的描述（可能为空），以及引用这个角色的若干剧本片段：剧本标题、梗概、\
该角色在剧本里的 traits 设定和台词。

你的职责是整理出这个角色可长期复用的两段文字，只写剧本能支撑的内容，不编造剧本里没有的经历：

1. description（角色描述）——用于反复生成这个角色的图片，规则沿用剧本角色设定：
{_CHARACTER_APPEARANCE_RULE}
- 多个剧本的设定冲突时，以最新的剧本（列表第一个）为准；作者已写的描述里与剧本不冲突的内容保留
- 300 字以内

2. voice_description（音色描述）——用于为这个角色挑选或设计配音音色：
- 依次写：性别、年龄感、音色质地（如清亮、低沉、沙哑、软糯）、音高、语速、说话习惯与常带情绪、\
口音（没有就不写）
- 从台词的措辞、句长、语气推断说话方式，例如短句多、反问多说明语气冷硬
- 不写角色经历和外貌，不写具体台词
- 120 字以内

只返回被要求的字段；没被要求的字段返回空字符串。

{JSON_INSTRUCTION}
格式：{{"description": "...", "voice_description": "..."}}"""

_FALLBACK: dict[str, Any] = {"description": "", "voice_description": ""}


@dataclass(frozen=True, slots=True)
class ScriptExcerpt:
    title: str
    logline: str
    traits: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CharacterProfileDraft:
    description: str | None
    voice_description: str | None


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def describe(
    session: Session,
    *,
    name: str,
    description: str | None,
    voice_description: str | None,
    scripts: list[ScriptExcerpt],
    fields: tuple[str, ...] = DESCRIBE_FIELDS,
    user_id: str | None = None,
) -> CharacterProfileDraft:
    """Drafts the requested `fields`; `None` for a field not requested.

    Raises `ProviderTemporaryFailure` when the model gave nothing usable for
    a requested field — the dialog shows the error and keeps the author's
    own text rather than presenting an empty "draft".
    """
    wanted = tuple(field for field in DESCRIBE_FIELDS if field in fields)
    payload = {
        "character_profile": "describe",
        "fields": list(wanted),
        "name": name,
        "current_description": description or "",
        "current_voice_description": voice_description or "",
        "scripts": [
            {
                "title": script.title,
                "logline": script.logline,
                "traits": script.traits,
                "lines": list(script.lines[:MAX_LINES_PER_SCRIPT]),
            }
            for script in scripts[:MAX_SCRIPTS_IN_PROMPT]
        ],
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=dict(_FALLBACK),
        user_id=user_id,
        agent_id=agent_skills_service.resolve_copy_agent_id(session),
        slot=CHARACTER_DESCRIBE_SLOT,
        max_tokens=DESCRIBE_MAX_TOKENS,
        temperature=DESCRIBE_TEMPERATURE,
    )
    drafted = {
        "description": _clean(outcome.data.get("description"), MAX_DESCRIPTION_LEN),
        "voice_description": _clean(
            outcome.data.get("voice_description"), MAX_VOICE_DESCRIPTION_LEN
        ),
    }
    if outcome.degraded or any(not drafted[field] for field in wanted):
        raise ProviderTemporaryFailure("AI 暂时无法生成角色描述，请稍后重试。")
    return CharacterProfileDraft(
        description=drafted["description"] if "description" in wanted else None,
        voice_description=(drafted["voice_description"] if "voice_description" in wanted else None),
    )


# ---- voice match (P7) -------------------------------------------------------------

VOICE_MATCH_MAX_TOKENS = 400
VOICE_MATCH_TEMPERATURE = 0.2

VOICE_MATCH_SYSTEM_PROMPT = f"""你是造浪平台的配音选角。你会收到一个角色的名称、音色描述，\
以及一份编号的可用预设音色清单（每条是「模型 / 音色名」，部分模型还支持语速 speed 或情绪 emotion）。

从清单里挑出最贴合音色描述的一条，只回它的编号：
- 先看性别和年龄感，再看音色质地与语气
- 只有该条目标明支持时才给 speed（0.25–4.0，1 为正常）或 emotion（只能取条目列出的值），否则省略
- reason 用一句话说明为什么选它（30 字以内）

{JSON_INSTRUCTION}
格式：{{"pick": 编号, "speed": 数字或省略, "emotion": 字符串或省略, "reason": "..."}}"""


@dataclass(frozen=True, slots=True)
class VoiceOption:
    model: str
    voice: str
    params: tuple[str, ...] = ()
    emotions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceMatch:
    option: VoiceOption
    speed: float | None
    emotion: str | None
    reason: str


def match_voice(
    session: Session,
    *,
    name: str,
    voice_description: str,
    options: list[VoiceOption],
    user_id: str | None = None,
) -> VoiceMatch:
    """The preset voice in `options` that best fits `voice_description`.
    Falls back to the first option (with no knobs) when the model's pick
    is unusable — the caller only ever gets a voice that exists."""
    if not options:
        raise ProviderTemporaryFailure("当前没有可用的预设音色模型。")
    listing = "\n".join(
        f"{index}. {option.model} / {option.voice}"
        + ("（支持 speed）" if "speed" in option.params else "")
        + (f"（支持 emotion：{'、'.join(option.emotions)}）" if option.emotions else "")
        for index, option in enumerate(options, start=1)
    )
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=VOICE_MATCH_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "voice_match": True,
                "name": name,
                "voice_description": voice_description,
                "options": listing,
            },
            ensure_ascii=False,
        ),
        fallback={"pick": 1, "reason": ""},
        user_id=user_id,
        agent_id=agent_skills_service.resolve_copy_agent_id(session),
        slot=VOICE_MATCH_SLOT,
        max_tokens=VOICE_MATCH_MAX_TOKENS,
        temperature=VOICE_MATCH_TEMPERATURE,
    )
    pick = outcome.data.get("pick")
    index = pick if isinstance(pick, int) and not isinstance(pick, bool) else 1
    if not 1 <= index <= len(options):
        index = 1
    option = options[index - 1]
    speed: float | None = None
    raw_speed = outcome.data.get("speed")
    if "speed" in option.params and isinstance(raw_speed, int | float):
        speed = min(max(float(raw_speed), 0.25), 4.0)
    raw_emotion = outcome.data.get("emotion")
    emotion = (
        raw_emotion if isinstance(raw_emotion, str) and raw_emotion in option.emotions else None
    )
    return VoiceMatch(
        option=option,
        speed=speed,
        emotion=emotion,
        reason=_clean(outcome.data.get("reason"), 60),
    )
