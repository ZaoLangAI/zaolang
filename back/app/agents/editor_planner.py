"""Editor planner: turns a cut + goal into a validated EditPlan command list."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.domain.editor import document as docs
from app.models import CutRevision, EpisodeCut
from app.models.enums import AgentName

SLOT = "timeline_edit_plan"

SYSTEM_PROMPT = f"""你是造浪平台的短剧时间线规划器。根据当前规范化时间线摘要与用户目标，
产出可执行的 EditCommand 列表。
规则：
- 只使用这些 type: insert_clip, delete_elements, move_elements, trim_element, split_element,
  set_clip_volume, set_clip_speed, insert_caption, update_caption, set_canvas, set_brand_overlay
- 时间全部是整数 tick，120000 ticks = 1 秒，禁止浮点秒
- 不要编造 asset_id；只能引用摘要里已有的素材
- 不要输出通用 path/value 更新
- commands 最多 40 条
- 涉及字幕时 caption_language 使用用户目标语言，缺省 zh-CN

{JSON_INSTRUCTION}
格式：{{"summary": string, "commands": [{{"type": string, "...": "..."}}], "warnings": string[]}}"""

FALLBACK: dict[str, Any] = {"summary": "", "commands": [], "warnings": []}


def plan_timeline(
    session: Session,
    *,
    user_id: str,
    cut: EpisodeCut,
    revision: CutRevision,
    goal: str,
    max_commands: int = 40,
    agent_id: str | None = None,
) -> AgentOutcome:
    payload = {
        "goal": goal,
        "max_commands": max_commands,
        "cut_id": cut.id,
        "revision_id": revision.id,
        "timeline": docs.timeline_summary(revision.document_json),
    }
    outcome = run_agent(
        session,
        agent_name=AgentName.EDITOR_PLANNER,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=FALLBACK,
        user_id=user_id,
        agent_id=agent_id,
        slot=SLOT,
    )
    commands = outcome.data.get("commands")
    if not isinstance(commands, list):
        outcome.data["commands"] = []
    else:
        outcome.data["commands"] = commands[: max(1, min(100, max_commands))]
    warnings = outcome.data.get("warnings")
    outcome.data["warnings"] = (
        [str(item) for item in warnings] if isinstance(warnings, list) else []
    )
    outcome.data["summary"] = str(outcome.data.get("summary") or goal)[:500]
    return outcome
