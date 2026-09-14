"""Matches a user's story to reference skills from the 「戏码与情绪」catalogue.

Two calls, deliberately: this module's cheap one picks *which* skills are
relevant from a titles-only shortlist, and the caller's own expensive one
(script drafting, prompt polish) receives the picked rows' descriptions as
reference material. Folding the shortlist into the main call instead would
put every candidate title in front of the big model on every single
invocation, for a decision the small one settles in a few dozen tokens.

Three properties this module holds onto, in the order they matter:

- **Advisory, never blocking.** Every failure path — an unreachable
  gateway, unparseable output, indices pointing nowhere — returns an empty
  list, and the caller proceeds exactly as it did before this module
  existed. Prompt polish is a live SSE stream; a matcher outage must cost
  the user a slower polish at worst, never a failed one.
- **Reference only.** What comes back is fed to an agent as material to
  read, not concatenated into the outgoing prompt. That is the whole reason
  a `drama` row is allowed to describe a tell no model may be able to render
  (see `docs/video-drama-scenes.md`): the agent judges what is worth
  writing for *this* story, where a blind append could not.
- **`drama` only.** `list_drama_candidates` scopes the shortlist to the
  seeded 「戏码与情绪」section. A `format` row would be unmatchable here by
  construction — a synopsis can point at 「雨夜追逐」, it can never point at
  「一镜一运镜」— and those rows already reach the prompt through
  `skill_library.service.apply_matching_format_skills` instead.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, run_agent
from app.domain.skill_library import service as skill_library_service
from app.models.enums import AgentName

logger = logging.getLogger(__name__)

SKILL_MATCH_SLOT = "skill_match"

# Mirrors `script_writing.service.MAX_REFERENCED_SKILLS`, which is the real
# constraint on the script side: the drafting prompt carries at most five
# reference entries, so asking for more here would only produce picks the
# caller drops.
MAX_MATCHED_SKILLS = 5

# The reply is a list of at most five integers. This is a slot *request*, not
# a ceiling (see `run_agent`), and exists only so a profile bound to a model
# with a large declared budget doesn't invite a reasoning model to narrate.
SKILL_MATCH_MAX_TOKENS = 256

# Low, unlike the polish slot's 0.7: two runs over the same story should pick
# the same references. This is a retrieval decision, not a creative one.
SKILL_MATCH_TEMPERATURE = 0.2

# The story text the picker sees. Generous enough for a full episode idea
# (`MAX_IDEA_LEN` is 20k) to still convey its shape after clipping, small
# enough that the shortlist stays the bulk of the prompt.
MAX_BRIEF_LEN = 3000

SYSTEM_PROMPT = f"""你是造浪平台的剧情技能匹配器。你会收到一段用户的剧情或画面描述，\
以及一份编号的技能清单——每一条是一种戏码场景（例如病房床前对峙、雨夜追逐）\
或一种情绪节拍（例如隐忍、反杀）的拍法。

你的唯一职责是从清单里挑出最多 {MAX_MATCHED_SKILLS} 条与这段剧情最相关的，只回编号。

判断标准，按优先级：
- 这段剧情里真的有这场戏或这种情绪吗？有才选。宁可少选也不要凑满五条
- 优先选剧情的主戏和主情绪，不要为了覆盖面把每个次要细节都配一条
- 场景型和情绪型可以混选，通常一段剧情会命中一到两个场景加两到三种情绪
- 同一场戏不要选两条近义的

剧情里一条都对不上时回空数组，这是正常且正确的结果。

{JSON_INSTRUCTION}
格式：{{"picks": [编号, 编号, ...]}}"""

# `run_agent` needs a fallback for unparseable output; an empty pick list is
# the same "matched nothing" the callers already handle.
_FALLBACK: dict[str, Any] = {"picks": []}


def select_reference_skills(
    session: Session,
    *,
    brief: str,
    limit: int = MAX_MATCHED_SKILLS,
    exclude_ids: tuple[str, ...] = (),
    user_id: str | None = None,
    agent_id: str | None = None,
) -> list[str]:
    """Up to `limit` seeded `drama` skill ids relevant to `brief`.

    `exclude_ids` drops skills the caller has already committed to — the
    user's own `@` references on the script path — before the shortlist is
    built, so the model never spends a pick re-choosing one of them and the
    caller never has to dedupe the two lists afterwards.

    Returns `[]` rather than raising on every failure: see the module
    docstring for why that is load-bearing rather than defensive habit.
    """
    text = (brief or "").strip()[:MAX_BRIEF_LEN]
    if not text or limit <= 0:
        return []

    excluded = set(exclude_ids)
    candidates = [
        (skill_id, title)
        for skill_id, title in skill_library_service.list_drama_candidates(session)
        if skill_id not in excluded
    ]
    if not candidates:
        return []

    shortlist = "\n".join(
        f"{index}. {title}" for index, (_, title) in enumerate(candidates, start=1)
    )
    user_prompt = f"剧情：\n{text}\n\n技能清单：\n{shortlist}"

    try:
        outcome = run_agent(
            session,
            agent_name=AgentName.COPY,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            fallback=dict(_FALLBACK),
            user_id=user_id,
            agent_id=agent_id,
            slot=SKILL_MATCH_SLOT,
            max_tokens=SKILL_MATCH_MAX_TOKENS,
            temperature=SKILL_MATCH_TEMPERATURE,
        )
    except Exception:
        # Broad on purpose. Anything the gateway, failover or bookkeeping can
        # raise degrades to "matched nothing" — the caller's own turn has not
        # started yet and must not inherit this failure.
        logger.warning("skill matcher call failed; continuing without references", exc_info=True)
        return []

    return _picked_ids(outcome.data.get("picks"), candidates, limit)


def _picked_ids(raw: Any, candidates: list[tuple[str, str]], limit: int) -> list[str]:
    """One-based indices into `candidates`, deduped and clipped to `limit`.

    Silently drops anything that isn't a usable index — a float, a title the
    model echoed back instead of its number, an index off the end. A model
    that returns four good picks and one hallucinated index should still
    contribute its four.
    """
    if not isinstance(raw, list):
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if isinstance(entry, bool) or not isinstance(entry, int):
            continue
        if not 1 <= entry <= len(candidates):
            continue
        skill_id = candidates[entry - 1][0]
        if skill_id in seen:
            continue
        picked.append(skill_id)
        seen.add(skill_id)
        if len(picked) >= limit:
            break
    return picked
