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
  set_clip_volume, set_clip_speed, insert_caption, update_caption, set_canvas, set_brand_overlay,
  add_track, remove_track, set_track_order, set_track_muted,
  add_effect, remove_effect, update_effect_params, set_clip_mask,
  set_keyframe, delete_keyframe, clear_keyframes, set_transition
- 时间全部是整数 tick，120000 ticks = 1 秒，禁止浮点秒
- 不要编造 asset_id；只能引用摘要里已有的素材
- 不要输出通用 path/value 更新
- commands 最多 40 条
- 涉及字幕时 caption_language 使用用户目标语言，缺省 zh-CN
- 时间线摘要里每条轨道都带 kind/order/label/muted；只有 video/audio 轨道能新增或删除，
  字幕轨与角标轨永远只有一条。优先复用已有轨道，只有确实需要同时呈现多段重叠内容
  （画中画、背景音乐叠加对白）时才用 add_track 新增，避免轨道无节制增多
- 特效 type 只能是 blur/brightness/contrast/saturate/grayscale 这五种（其余一律不支持）；
  add_effect 的 effect 形如 {{"type": "blur", "params": {{"intensity": 20}}}}（blur 用 intensity
  0-100，其余用 amount 百分比、100 为不变）；remove_effect/update_effect_params 用 effect_index
  定位（时间线摘要里每个元素的 effects 数组下标）
- set_clip_mask 的 mask 形如 {{"shape": "rect"|"ellipse", "x_milli", "y_milli", "width_milli",
  "height_milli", "feather_millipercent"}}（毫分比，1000 = 画布对应边的 100%），或直接传
  null 以清除蒙版
- 关键帧是粗粒度的（用户手动打点，不是逐帧动画）。property 只能是这五种之一：opacity、
  transform.x_milli、transform.y_milli、transform.scale_millipercent、
  transform.rotation_millidegrees。set_keyframe 需要 element_id/property/at_ticks/value；
  opacity 取值 0-100000（毫分比）；transform.x_milli/y_milli 取值 -2000 到 2000（画布对应边的
  毫分比偏移）；transform.scale_millipercent 取值 10000-500000（100000 为原始大小）；
  transform.rotation_millidegrees 取值 -180000 到 180000（毫度）。delete_keyframe 按
  element_id/property/at_ticks 精确删除一个关键帧；clear_keyframes 按 element_id/property
  清空整条动画通道，恢复为静态值
- insert_clip 可选 element_type: "clip"（默认）或 "sticker"，贴纸和普通片段字段完全一样，
  只是视觉角色不同
- 转场不是新建轨道或元素，而是同一轨道上相邻两个片段自然重叠出来的：先用 trim_element/
  move_elements 让下一个片段的开头与上一个片段的结尾重叠一段时间，再用 set_transition
  （element_id/edge: "in"|"out"/transition）在重叠一侧的片段上标注
  {{"type": "crossfade"|"dip_to_black", "duration_ticks"}}，duration_ticks 不能超过该元素自身
  时长，也不应超过两片段实际重叠的时长；传 transition: null 可清除该侧转场。crossfade 是两个
  画面透明度互补叠化，dip_to_black 是先淡出到黑再从黑淡入，不要给出超出片段本身或重叠时长的
  转场时长

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
