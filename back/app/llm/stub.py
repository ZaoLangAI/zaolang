"""Deterministic agent responses used by tests, CI and the degraded path.

The stub is not a mock that returns a fixed blob: it applies the same rules the
real agents are instructed to follow, so a test asserting "unsafe prompts are
rejected" is still testing the product rule rather than a hard-coded string.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.llm.normalize import NormalizedResponse
from app.models.enums import AgentName

# Terms that must produce a hard rejection regardless of gateway availability.
BLOCKED_TERMS = (
    "未成年",
    "minor",
    "child sexual",
    "亲密",
    "real person nude",
    "政治领导人",
    "deepfake politician",
)

SENSITIVE_TERMS = ("血腥", "gore", "暴力", "violence", "武器", "weapon", "斗殴")

# A literal marker rather than a length threshold: unlike `copywriter.clarify`
# (only called on demand, pre-submit, by the shortform studio), the planner's
# `clarify` slot now runs by default on every job through `execute_planning`
# (`PlanningConfig.allow_followup_question` defaults to `True`). The test
# suite is full of short placeholder prompts ("测试", "一只猫", "海雾" ...)
# that a length-based heuristic would flag as needing clarification, silently
# suspending dozens of unrelated tests at `AWAITING_INPUT`. Opting into the
# suspend path in a test is therefore explicit: include this marker.
PLANNER_CLARIFY_MARKER = "需要追问"


def stub_completion(
    *, agent_name: str, messages: list[dict[str, str]], model: str
) -> NormalizedResponse:
    # Only the user turn is inspected: a system prompt that spells out what is
    # forbidden would otherwise trip the very rules it describes.
    prompt = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
    payload = _dispatch(agent_name, prompt)
    text = json.dumps(payload, ensure_ascii=False)
    return NormalizedResponse(
        text=text,
        data=payload,
        finish_reason="stop",
        prompt_tokens=len(prompt) // 4,
        completion_tokens=len(text) // 4,
        model=f"stub:{model}",
    )


def _dispatch(agent_name: str, prompt: str) -> dict[str, Any]:
    if agent_name == AgentName.SAFETY:
        return _safety(prompt)
    if agent_name == AgentName.PLANNER:
        return _planner(prompt)
    if agent_name == AgentName.QUALITY:
        return _quality(prompt)
    if agent_name == AgentName.COPY:
        return _copy(prompt)
    if agent_name == AgentName.INTENT_ROUTER:
        return _intent_router(prompt)
    if agent_name == AgentName.EDITOR_PLANNER:
        return _editor_planner(prompt)
    # An operator-created role (run by the `custom_agent` node): the stub has
    # no idea what it was told to judge, so it returns the neutral shape
    # `app.agents.custom` declares rather than a fabricated verdict.
    return {"verdict": "unknown", "confidence": 0.0, "notes": "stub_custom_agent"}


def _safety(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    for term in BLOCKED_TERMS:
        if term.lower() in lowered:
            return {
                "decision": "reject",
                "categories": ["prohibited_content"],
                "reason_code": "PROHIBITED_CONTENT",
                # User-facing copy never quotes the matched term back.
                "public_message": "内容未通过安全检查，请调整描述后重试。",
            }
    for term in SENSITIVE_TERMS:
        if term.lower() in lowered:
            return {
                "decision": "needs_review",
                "categories": ["sensitive_content"],
                "reason_code": "SENSITIVE_CONTENT",
                "public_message": "内容需要人工复核，稍后会通知你结果。",
            }
    return {"decision": "approve", "categories": [], "reason_code": None, "public_message": ""}


def _planner(prompt: str) -> dict[str, Any]:
    # `plan` and `clarify` share one agent identity, so the stub tells them
    # apart by shape: `plan`'s user turn always carries `requested_operation`
    # (even when its value is `None`), `clarify`'s carries only `intent`.
    try:
        payload = json.loads(prompt)
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict) and "requested_operation" not in payload:
        return _planner_clarify(str(payload.get("intent", "")))
    return _planner_plan(prompt)


def _planner_plan(prompt: str) -> dict[str, Any]:
    # Stable pseudo-randomness keyed by the prompt keeps plans reproducible.
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    wants_video = any(word in prompt for word in ("视频", "video", "动态", "motion"))
    return {
        "operation": "text_to_video" if wants_video else "text_to_image",
        "steps": [
            {"name": "compose_prompt", "detail": "整理主体、风格与镜头语言"},
            {"name": "select_reference", "detail": "复用来源作品的构图参数"},
            {"name": "render", "detail": "提交渲染并轮询进度"},
        ],
        "recommended_tier": "standard",
        "prompt_enhancements": ["电影感布光", "浅景深"],
        "negative_prompt_suggestions": ["肢体畸变", "画面抖动伪影"],
        "plan_hash": digest[:16],
    }


def _planner_clarify(text: str) -> dict[str, Any]:
    """Mirrors `planner.CLARIFY_SYSTEM_PROMPT`'s minimal-info check.

    See `PLANNER_CLARIFY_MARKER` for why this is a marker rather than the
    length threshold `_copy_clarify` uses.
    """
    if PLANNER_CLARIFY_MARKER not in text:
        return {"needs_clarification": False, "questions": []}
    return {
        "needs_clarification": True,
        "questions": [
            {
                "id": "subject_count",
                "kind": "single_choice",
                "prompt": "画面里大约有多少个主体？",
                "options": [
                    {"value": "one", "label": "1 个"},
                    {"value": "few", "label": "2-5 个"},
                    {"value": "crowd", "label": "5 个以上"},
                ],
                "required": True,
            },
            {
                "id": "camera",
                "kind": "free_text",
                "prompt": "希望用什么镜头语言呈现？",
                "options": [],
                "required": False,
            },
        ],
    }


def _quality(prompt: str) -> dict[str, Any]:
    failed = "损坏" in prompt or "corrupt" in prompt.lower()
    return {
        "verdict": "fail" if failed else "pass",
        "scores": {
            "prompt_alignment": 0.3 if failed else 0.86,
            "technical_quality": 0.4 if failed else 0.9,
            "aesthetic": 0.35 if failed else 0.82,
        },
        "should_retry": failed,
        "notes": "输出与描述不匹配" if failed else "符合预期",
    }


VIDEO_OPERATIONS = ("text_to_video", "image_to_video", "video_to_video")


def _intent_router(prompt: str) -> dict[str, Any]:
    """Backs both `intent_router.classify` and `.select_provider` calls.

    The two are told apart by shape, not by a separate agent name: only
    `select_provider`'s payload carries a `candidates` list.
    """
    try:
        payload = json.loads(prompt)
    except (TypeError, ValueError):
        payload = {}

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        # Cheapest effective cost wins, tie-broken by name — deterministic
        # and independent of dict/set ordering so routing tests stay stable
        # without a real model in the loop. The request-level `cost_bias`
        # carried alongside the candidates is deliberately ignored here: it
        # is a cost *preference* a real model weighs against quality, and
        # folding it into a stub formula would make the offline path behave
        # like the weighted router that was removed on purpose.
        winner = min(
            candidates,
            key=lambda c: (c.get("effective_cost", 0), str(c.get("provider", ""))),
        )
        return {
            "selected_provider": winner.get("provider"),
            "rationale": "stub_lowest_effective_cost",
        }

    requested_tier = payload.get("requested_tier")
    # Mirrors `SYSTEM_PROMPT`'s video-specific dimension: a short prompt
    # naming multi-subject/action content (a fight, a chase, weapons) is not
    # `simple` just because the text is short — the hard part is motion, not
    # word count. Still never touches `suggested_quality_tier`: the stub's
    # job is staying a safe, deterministic "no downgrade" default, not
    # reproducing the real model's tier judgement.
    operation = str(payload.get("operation") or "")
    intent_text = str(payload.get("intent") or "").lower()
    is_action_heavy_video = operation in VIDEO_OPERATIONS and any(
        term in intent_text for term in SENSITIVE_TERMS
    )
    return {
        "complexity": "complex" if is_action_heavy_video else "moderate",
        "suggested_quality_tier": requested_tier or "standard",
        "cost_bias": 0.0,
        "rationale": "stub_no_downgrade",
    }


def _copy(prompt: str) -> dict[str, Any]:
    # `suggest`, `enhance` and `clarify` share one agent identity, so the stub
    # tells them apart by shape: `enhance`'s user turn carries `max_length`,
    # `suggest`'s always carries `locale`, `clarify`'s carries only `prompt`.
    try:
        payload = json.loads(prompt)
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict):
        if "max_length" in payload:
            return _copy_enhance(str(payload.get("prompt", "")))
        if "locale" in payload:
            digest = hashlib.sha256(prompt.encode()).hexdigest()[:6]
            return {
                "title": f"未命名作品 {digest}",
                "description": "由造浪智能网关生成的作品，保留完整创作链与署名。",
                "tags": ["cinematic", "ai-generated", "remix"],
            }
        if "prompt" in payload:
            return _copy_clarify(str(payload.get("prompt", "")))

    digest = hashlib.sha256(prompt.encode()).hexdigest()[:6]
    return {
        "title": f"未命名作品 {digest}",
        "description": "由造浪智能网关生成的作品，保留完整创作链与署名。",
        "tags": ["cinematic", "ai-generated", "remix"],
    }


def _copy_enhance(text: str) -> dict[str, Any]:
    """Mirrors `copywriter.ENHANCE_SYSTEM_PROMPT`'s detail-assessment rule."""
    stripped = text.strip()
    if len(stripped) < 20:
        detail_level = "sparse"
        feedback = "描述比较简略，建议补充主体动作、场景与镜头细节。"
        enhanced = f"{stripped}，特写镜头，柔和自然光，浅景深，画面细节丰富" if stripped else stripped
    elif len(stripped) < 60:
        detail_level = "adequate"
        feedback = "已有基本画面信息，补充一些氛围与镜头语言会更具体。"
        enhanced = f"{stripped}，运镜舒缓，光影层次分明"
    else:
        detail_level = "detailed"
        feedback = "描述已经足够具体，这里只做措辞上的微调。"
        enhanced = stripped
    return {"detail_level": detail_level, "feedback": feedback, "prompt": enhanced}


def _copy_clarify(text: str) -> dict[str, Any]:
    """Mirrors `copywriter.CLARIFY_SYSTEM_PROMPT`'s minimal-info check.

    Same length threshold as `_copy_enhance`'s `sparse` bucket: short
    descriptions are missing enough of subject/scene/action/camera that a real
    model would ask, everything else is specific enough to skip straight to
    generation.
    """
    stripped = text.strip()
    if len(stripped) >= 20:
        return {"needs_clarification": False, "questions": []}
    return {
        "needs_clarification": True,
        "questions": [
            {
                "id": "scene",
                "kind": "single_choice",
                "prompt": "画面发生在什么场景？",
                "options": [
                    {"value": "indoor", "label": "室内"},
                    {"value": "outdoor", "label": "室外"},
                ],
                "required": True,
            },
            {
                "id": "action",
                "kind": "free_text",
                "prompt": "主体在做什么动作？",
                "options": [],
                "required": False,
            },
        ],
    }


def _editor_planner(prompt: str) -> dict[str, Any]:
    """Deterministic empty plan: the user must confirm before any command lands."""
    del prompt
    return {
        "summary": "stub: 未改动时间线，等待作者确认目标后再生成命令。",
        "commands": [],
        "warnings": ["stub_no_commands"],
    }
