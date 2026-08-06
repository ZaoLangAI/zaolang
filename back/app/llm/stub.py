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

SENSITIVE_TERMS = ("血腥", "gore", "暴力", "violence", "武器", "weapon")


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
    return {"result": "ok"}


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
        "plan_hash": digest[:16],
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
        # without a real model in the loop.
        winner = min(
            candidates,
            key=lambda c: (c.get("effective_cost", 0), str(c.get("provider", ""))),
        )
        return {
            "selected_provider": winner.get("provider"),
            "rationale": "stub_lowest_effective_cost",
        }

    requested_tier = payload.get("requested_tier")
    return {
        "complexity": "moderate",
        "suggested_quality_tier": requested_tier or "standard",
        "cost_bias": 0.0,
        "rationale": "stub_no_downgrade",
    }


def _copy(prompt: str) -> dict[str, Any]:
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:6]
    return {
        "title": f"未命名作品 {digest}",
        "description": "由造浪智能网关生成的作品，保留完整创作链与署名。",
        "tags": ["cinematic", "ai-generated", "remix"],
    }
