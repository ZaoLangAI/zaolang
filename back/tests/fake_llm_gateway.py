"""Deterministic replacement for `app.llm.client.complete`/`stream_complete`.

Installed by the autouse fixture in `conftest.py` for every test except the
ones exercising the real gateway plumbing (`@pytest.mark.live`) or the
gateway's own failover/circuit-breaker logic against a mocked transport
(`@pytest.mark.real_gateway_seams`). Production code has exactly one calling
behaviour now — call the real, admin-configured gateway or raise
`ProviderTemporaryFailure` — so this fake exists purely to keep the rest of
the suite deterministic, key-free and offline, the same job `app/llm/stub.py`
used to do before the `stub`/`auto` modes were removed.

The fake is not a mock that returns a fixed blob: it applies the same rules
the real agents are instructed to follow, so a test asserting "unsafe prompts
are rejected" is still testing the product rule rather than a hard-coded
string.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.llm.client import NO_ENDPOINT_ID, LlmCallResult, StreamChunk, StreamResult
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


def fake_complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    expect_json: bool = True,
    reasoning_model: bool = False,
    preferred_endpoint_ids: Sequence[str] = (),
    on_chunk: Any = None,
) -> LlmCallResult:
    """Signature-compatible with `app.llm.client.complete`; ignores every
    gateway-selection argument (`session`/`temperature`/`preferred_endpoint_ids`/
    ...) since there is no real endpoint behind this call.

    Deliberately does not replicate the real client's "unbound model raises"
    rule: almost none of the suite binds a catalog model to every agent it
    exercises, so this fake stays permissive the way `app.llm.stub` always
    was. Tests that specifically need to observe the real "unbound → 503"
    behaviour opt out of this fake with `@pytest.mark.real_gateway_seams`
    instead (see `tests/unit/test_agent_gateway.py` and
    `tests/integration/test_prompts_api.py`).
    """
    del session, max_tokens, temperature, reasoning_model, preferred_endpoint_ids, on_chunk
    prompt = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
    payload = _dispatch(agent_name, prompt)
    text = json.dumps(payload, ensure_ascii=False)
    response = NormalizedResponse(
        text=text,
        data=payload if expect_json else None,
        finish_reason="stop",
        prompt_tokens=len(prompt) // 4,
        completion_tokens=len(text) // 4,
        model=model or "fake-llm",
    )
    return LlmCallResult(response=response, latency_ms=0, endpoint_id=NO_ENDPOINT_ID)


def fake_stream_complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[dict[str, str]],
    result: StreamResult,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    reasoning_model: bool = False,
    preferred_endpoint_ids: Sequence[str] = (),
    is_usable: Any = None,
    expect_json: bool = False,
) -> Iterator[StreamChunk]:
    """Signature-compatible with `app.llm.client.stream_complete`.

    Yields a single `kind="thinking"` chunk followed by a single
    `kind="content"` chunk — enough for a caller that forwards `StreamChunk`s
    by `.kind` (see `app.domain.script_writing.service`) to exercise both
    branches, without needing every one of this fake's many callers to know
    or care about the split.
    """
    del (
        session,
        max_tokens,
        temperature,
        reasoning_model,
        preferred_endpoint_ids,
        is_usable,
        expect_json,
    )
    text = _dispatch_stream(agent_name, messages)
    thinking = f"fake:{agent_name} 正在构思……"
    yield StreamChunk(kind="thinking", text=thinking)
    yield StreamChunk(kind="content", text=text)
    result.text = text
    result.thinking = thinking
    result.endpoint_id = NO_ENDPOINT_ID
    result.model = model or "fake-llm"
    result.prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
    result.completion_tokens = len(text) // 4
    result.latency_ms = 0


def _dispatch_stream(agent_name: str, messages: list[dict[str, str]]) -> str:
    """Deterministic mixed prose+JSON text for a streaming turn.

    Only the `copy` role's `script_draft`/`script_revise` slots stream today
    (see `app.agents.copywriter.stream_script_turn`) — everything else falls
    back to the plain JSON-mode payload serialised as text, so a misrouted
    call still gets something deterministic instead of silence.
    """
    prompt = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
    if agent_name == AgentName.COPY:
        try:
            payload = json.loads(prompt)
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict) and "current_script" in payload:
            return _copy_stream_script_revise(payload)
        if isinstance(payload, dict) and "idea" in payload:
            return _copy_stream_script_draft(payload)
    data = _dispatch(agent_name, prompt)
    return json.dumps(data, ensure_ascii=False)


def _copy_stream_script_draft(payload: dict[str, Any]) -> str:
    """Mirrors `copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT`'s output shape: a short
    change summary, then a fenced JSON block with the full script document."""
    idea = str(payload.get("idea") or "").strip()
    title = str(payload.get("title") or "").strip()
    digest = hashlib.sha256(idea.encode()).hexdigest()[:6]
    script = {
        "title": title or (idea[:24] if idea else f"未命名短剧 {digest}"),
        "logline": idea or "一段关于选择与代价的短剧。",
        "characters": [
            {
                "name": "林夏",
                "traits": "年轻女性，二十出头，肤色偏白，齐肩黑发，穿便利店店员制服；"
                "外冷内热，藏着不能说的秘密",
            }
        ],
        "scenes": [
            {
                "heading": "第一场 · 便利店 - 夜",
                "blocks": [
                    {
                        "type": "scene",
                        "character": None,
                        "text": "深夜的便利店，日光灯嗡嗡作响，货架投下长长的影子。",
                    },
                    {
                        "type": "camera",
                        "character": None,
                        "text": "镜头缓慢推近，从自动门口移向收银台。",
                    },
                    {
                        "type": "action",
                        "character": None,
                        "text": "林夏机械地擦拭着柜台，目光时不时飘向门口。",
                    },
                    {
                        "type": "dialogue",
                        "character": "林夏",
                        "text": "（自语）今天，会是最后一天吗。",
                    },
                    {
                        "type": "breakpoint",
                        "character": None,
                        "text": "建议在此处切分：前段约 15 秒台词与动作，符合单条生成 ≤30 秒上限。",
                    },
                ],
            }
        ],
    }
    summary = f"已根据你的创意生成剧本初稿（fake:{digest}）。"
    return f"{summary}\n```json\n{json.dumps(script, ensure_ascii=False)}\n```"


def _copy_stream_script_revise(payload: dict[str, Any]) -> str:
    """Deterministically appends a scene reflecting the user's message, so a
    test asserting "the revision changed" observes real movement instead of
    an unchanged echo — unlike `_editor_planner`'s "no commands" fake, a
    script revision with literally no change would look like a broken turn."""
    message = str(payload.get("message") or "").strip()
    current = payload.get("current_script")
    script: dict[str, Any] = (
        deepcopy(current)
        if isinstance(current, dict)
        else {"title": "", "logline": "", "characters": [], "scenes": []}
    )
    scenes = script.get("scenes")
    if not isinstance(scenes, list):
        scenes = []
        script["scenes"] = scenes
    digest = hashlib.sha256(message.encode()).hexdigest()[:6]
    scenes.append(
        {
            "heading": f"第{len(scenes) + 1}场 · 修改 - 日",
            "blocks": [
                {
                    "type": "action",
                    "character": None,
                    "text": message[:160] or "（fake 未提供修改说明）",
                }
            ],
        }
    )
    summary = f"已根据你的意见修改剧本（fake:{digest}）。"
    return f"{summary}\n```json\n{json.dumps(script, ensure_ascii=False)}\n```"


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
    # An operator-created role (run by the `custom_agent` node): the fake has
    # no idea what it was told to judge, so it returns the neutral shape
    # `app.agents.custom` declares rather than a fabricated verdict.
    return {"verdict": "unknown", "confidence": 0.0, "notes": "fake_custom_agent"}


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
    # `plan`, `clarify` and `asset_plan` share one agent identity, so dispatch
    # tells them apart by shape: `plan`'s user turn always carries
    # `requested_operation` (even when its value is `None`), `asset_plan`'s
    # always carries `asset_kind`, `clarify`'s carries only `intent`.
    try:
        payload = json.loads(prompt)
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict) and "asset_kind" in payload:
        return _planner_asset_plan(payload)
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


# Keyed by `character_view` for `asset_kind == "character"`, by `asset_kind`
# itself for everything else — mirrors `planner._CHARACTER_VIEW_BRIEF` /
# `_ASSET_KIND_BRIEF`'s two-tier lookup.
_CHARACTER_VIEW_NEGATIVES: dict[str, list[str]] = {
    "front": ["多人入镜", "半身裁切"],
    "side": ["多人入镜", "半身裁切", "五官被头发遮挡"],
    "back": ["多人入镜", "露出正面五官"],
}
_ASSET_KIND_NEGATIVES: dict[str, list[str]] = {
    "scene": ["人物遮挡主体", "画面过曝"],
    "cover": ["文字遮挡关键主体", "画面杂乱"],
}


def _planner_asset_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Mirrors `planner.ASSET_PLAN_SYSTEM_PROMPT`'s per-kind rules: a stable
    subject name, consistency-preserving enhancements when a prior view's
    description is available in `source_params`, and a kind-appropriate
    negative list."""
    intent = str(payload.get("intent") or "").strip()
    asset_kind = str(payload.get("asset_kind") or "")
    character_view = payload.get("character_view")
    source_params = payload.get("source_params")
    digest = hashlib.sha256(intent.encode()).hexdigest()[:6]
    subject_name = intent[:12] if intent else f"新角色 {digest}"

    enhancements = ["电影感布光", "浅景深"]
    if isinstance(source_params, dict):
        prior_description = source_params.get("subject_description") or source_params.get(
            "prior_view_description"
        )
        if prior_description:
            enhancements.append(f"保持与已有视角一致：{prior_description}")

    negatives = (
        _CHARACTER_VIEW_NEGATIVES.get(str(character_view), [])
        if asset_kind == "character" and character_view
        else _ASSET_KIND_NEGATIVES.get(asset_kind, [])
    )
    return {
        "subject_name": subject_name,
        "prompt_enhancements": enhancements,
        "negative_prompt_suggestions": list(negatives),
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
        # folding it into a fake formula would make the offline path behave
        # like the weighted router that was removed on purpose.
        winner = min(
            candidates,
            key=lambda c: (c.get("effective_cost_micro_usd", 0), str(c.get("provider", ""))),
        )
        return {
            "selected_provider": winner.get("provider"),
            "rationale": "fake_lowest_effective_cost",
        }

    requested_tier = payload.get("requested_tier")
    # Mirrors `SYSTEM_PROMPT`'s video-specific dimension: a short prompt
    # naming multi-subject/action content (a fight, a chase, weapons) is not
    # `simple` just because the text is short — the hard part is motion, not
    # word count. Still never touches `suggested_quality_tier`: this fake's
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
        "rationale": "fake_no_downgrade",
    }


def _copy(prompt: str) -> dict[str, Any]:
    # `suggest`, `enhance` and `clarify` share one agent identity, so dispatch
    # tells them apart by shape: `enhance`'s user turn carries `max_length`,
    # `suggest`'s always carries `locale`, `clarify`'s carries only `prompt`.
    try:
        payload = json.loads(prompt)
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict):
        if "max_length" in payload:
            return _copy_enhance(payload)
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


# Mirrors `copywriter.VIDEO_DIMENSIONS` / `.IMAGE_DIMENSIONS`. Duplicated rather
# than imported because `app.agents` imports this module's package, not the
# other way round; `tests/unit/test_prompt_enhance.py` asserts they stay equal.
_ENHANCE_VIDEO_DIMENSIONS = ("subject", "scene", "action", "camera", "lighting", "mood", "pacing")
_ENHANCE_IMAGE_DIMENSIONS = ("subject", "scene", "composition", "lighting", "style", "detail")

# One deterministic phrase per direction, so an iterating test can tell which
# round it is looking at. `more_concise` adds nothing on purpose: shortening is
# the one direction that must not append.
_ENHANCE_DIRECTION_PHRASES = {
    "more_specific": "主体轮廓与材质纹理清晰可辨",
    "more_concise": "",
    "stronger_camera": "镜头缓慢推近",
    "stronger_lighting": "逆光轮廓光",
    "more_dramatic": "明暗对比强烈",
}


def _copy_enhance(payload: dict[str, Any]) -> dict[str, Any]:
    """Mirrors `copywriter.ENHANCE_SYSTEM_PROMPT`'s diagnosis rules.

    Length stands in for the real model's judgement, but everything derived
    from it follows the same rules the prompt states: the dimension set
    depends on the medium, and `detail_level` follows from the statuses
    (two or more `missing` is sparse, any `weak` is adequate, all `ok` is
    detailed) rather than being decided separately.
    """
    stripped = str(payload.get("prompt", "")).strip()
    operation = str(payload.get("operation") or "")
    direction = str(payload.get("direction") or "")
    instruction = str(payload.get("instruction") or "").strip()
    keys = (
        _ENHANCE_IMAGE_DIMENSIONS
        if operation in ("text_to_image", "image_to_image")
        else _ENHANCE_VIDEO_DIMENSIONS
    )

    if len(stripped) < 20:
        detail_level = "sparse"
        feedback = "描述比较简略，先把主体动作、场景与镜头补上，生成结果会稳定很多。"
        additions = ["特写镜头", "柔和自然光", "浅景深", "画面细节丰富"]
        # Two `missing` is exactly what makes this bucket sparse.
        statuses = ["missing", "missing"] + ["weak"] * (len(keys) - 2)
    elif len(stripped) < 60:
        detail_level = "adequate"
        feedback = "基本画面信息已经齐了，再补一点氛围与镜头语言会更具体。"
        additions = ["运镜舒缓", "光影层次分明"]
        statuses = ["ok", "ok"] + ["weak"] * (len(keys) - 2)
    else:
        detail_level = "detailed"
        feedback = "描述已经足够具体，这里只做措辞上的微调。"
        additions = []
        statuses = ["ok"] * len(keys)

    # An iterating round follows the requested direction only, instead of
    # re-running the first-round padding.
    if direction or instruction:
        phrase = _ENHANCE_DIRECTION_PHRASES.get(direction, "") if direction else ""
        if instruction and not phrase:
            phrase = instruction[:20]
        additions = [phrase] if phrase else []
        feedback = "已按你这一轮的要求调整。"

    enhanced = "，".join([stripped, *additions]) if stripped and additions else stripped
    return {
        "detail_level": detail_level,
        "feedback": feedback,
        "prompt": enhanced,
        "dimensions": [
            {"key": key, "status": status, "hint": _ENHANCE_HINTS[status]}
            for key, status in zip(keys, statuses, strict=True)
        ],
        "additions": additions,
    }


_ENHANCE_HINTS = {
    "missing": "这一项还没写，补一句具体的就能明显改善画面。",
    "weak": "这一项写了但还笼统，可以再具体一层。",
    "ok": "这一项已经足够具体，可以直接生成。",
}


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
        "summary": "fake: 未改动时间线，等待作者确认目标后再生成命令。",
        "commands": [],
        "warnings": ["fake_no_commands"],
    }
