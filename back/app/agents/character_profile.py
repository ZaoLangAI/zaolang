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
