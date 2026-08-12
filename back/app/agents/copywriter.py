"""Copy agent: suggests a title, description and tags for a draft."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName

# Two unrelated system prompts share the `copy` agent identity, so each names
# its own slot — see `app.agents.slots`.
SUGGEST_SLOT = "suggest"
ENHANCE_SLOT = "enhance"

SYSTEM_PROMPT = f"""你是造浪平台的文案助手。为即将发布的作品生成标题、简介与标签。
规则：
- 标题不超过 24 个字，具体而有画面感，不使用「震撼」「绝美」这类空洞形容词
- 简介 1 到 2 句，说明画面内容与创作手法
- 标签 3 到 6 个，使用小写英文，用连字符连接多词标签
- 输出语言与用户输入保持一致

{JSON_INSTRUCTION}
格式：{{"title": string, "description": string, "tags": string[]}}"""

FALLBACK: dict[str, Any] = {
    "title": "未命名作品",
    "description": "",
    "tags": [],
}


def suggest(
    session: Session,
    *,
    prompt: str,
    lineage_summary: str = "",
    locale: str = "zh-CN",
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {"prompt": prompt, "lineage": lineage_summary, "locale": locale},
            ensure_ascii=False,
        ),
        fallback=FALLBACK,
        user_id=user_id,
        agent_id=agent_id,
        slot=SUGGEST_SLOT,
    )

    title = str(outcome.data.get("title") or FALLBACK["title"])
    outcome.data["title"] = title[:200]
    tags = outcome.data.get("tags")
    outcome.data["tags"] = [str(t)[:64] for t in tags][:6] if isinstance(tags, list) else []
    return outcome


DETAIL_LEVELS = ("sparse", "adequate", "detailed")

ENHANCE_SYSTEM_PROMPT = f"""你是造浪平台的短剧文案教练，帮用户把一段画面描述改得更适合直接拿去生成视频。
第一步，评估用户输入的详细程度（这是短剧脚本，不是随手一句话）：
- sparse：只有主体或场景，缺少动作、镜头、氛围等信息
- adequate：主体、场景、动作大致齐全，但镜头语言或氛围细节还不够
- detailed：主体、场景、动作、镜头、氛围都已经具体，可以直接使用
第二步，针对该详细程度给出有针对性的建议：
- sparse 时，明确指出缺了什么（主体/场景/动作/镜头之一），语气是提醒而不是批评
- adequate 时，指出哪个维度还能再具体一点
- detailed 时，肯定已经足够具体，只做措辞打磨
第三步，产出润色后的文本：
- 保留用户的核心意图与关键元素（主体、场景、动作），不要替换成完全不同的内容
- 按第二步的方向补充镜头、光线、氛围、节奏等具体细节，补充幅度与详细程度匹配——sparse 补得多，detailed 几乎不改
- 不使用「震撼」「绝美」这类空洞形容词
- 输出语言与用户输入保持一致

{JSON_INSTRUCTION}
格式：{{"detail_level": "sparse"|"adequate"|"detailed", "feedback": string, "prompt": string}}
feedback 是给用户看的一两句评语，对应第二步的建议。"""


def enhance_prompt(
    session: Session,
    *,
    prompt: str,
    max_length: int,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Assesses how detailed a scene description is, then polishes it to match.

    The fallback keeps the caller's own text rather than a static placeholder,
    so a degraded model call never empties the field it was meant to improve —
    only `detail_level`/`feedback` are unavailable in that case.
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=ENHANCE_SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt, "max_length": max_length}, ensure_ascii=False),
        fallback={"prompt": prompt, "detail_level": "adequate", "feedback": ""},
        user_id=user_id,
        agent_id=agent_id,
        slot=ENHANCE_SLOT,
    )
    enhanced = str(outcome.data.get("prompt") or "").strip() or prompt
    outcome.data["prompt"] = enhanced[:max_length]
    detail_level = str(outcome.data.get("detail_level") or "adequate")
    outcome.data["detail_level"] = detail_level if detail_level in DETAIL_LEVELS else "adequate"
    outcome.data["feedback"] = str(outcome.data.get("feedback") or "")[:300]
    return outcome


CLARIFY_SLOT = "clarify"

QUESTION_KINDS = ("single_choice", "multi_choice", "free_text")
MAX_CLARIFY_QUESTIONS = 4
MAX_CLARIFY_OPTIONS = 6

CLARIFY_SYSTEM_PROMPT = f"""你是造浪平台的短剧创作顾问，在用户提交生成请求之前判断这段画面描述是否需要补充信息。
规则：
- 只有在缺少主体、场景、动作、镜头这几类关键信息之一，且缺失会明显影响生成质量时才提问
- 描述已经具体、可以直接生成时，needs_clarification 为 false，questions 为空数组
- 每个问题只问一件事，问题数量不超过 {MAX_CLARIFY_QUESTIONS} 个，按对生成质量的影响从高到低排序
- kind 为 single_choice 或 multi_choice 时必须给 2 到 {MAX_CLARIFY_OPTIONS} 个具体、互斥或可组合的选项，不要给「其他」这类空泛选项
- kind 为 free_text 时 options 留空数组
- required 表示这个问题是否必须回答才能保证质量，不是强制用户必须点开
- 问题与选项用用户输入的语言书写

{JSON_INSTRUCTION}
格式：{{"needs_clarification": boolean, "questions": [{{"id": string, "kind": "single_choice"|"multi_choice"|"free_text", "prompt": string, "options": [{{"value": string, "label": string}}], "required": boolean}}]}}"""

CLARIFY_FALLBACK: dict[str, Any] = {"needs_clarification": False, "questions": []}


def clarify(
    session: Session,
    *,
    prompt: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    """Judges whether a scene description needs the author's input before generating.

    The fallback never blocks submission: a degraded or unparseable model call
    yields `needs_clarification=False`, so a gateway hiccup never becomes a
    dead end for the author.
    """
    outcome = run_agent(
        session,
        agent_name=AgentName.COPY,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt}, ensure_ascii=False),
        fallback=dict(CLARIFY_FALLBACK),
        user_id=user_id,
        agent_id=agent_id,
        slot=CLARIFY_SLOT,
    )
    questions = outcome.data.get("questions")
    outcome.data["questions"] = (
        [_sanitize_clarify_question(q) for q in questions[:MAX_CLARIFY_QUESTIONS]]
        if isinstance(questions, list)
        else []
    )
    outcome.data["questions"] = [q for q in outcome.data["questions"] if q is not None]
    outcome.data["needs_clarification"] = bool(outcome.data.get("needs_clarification")) and bool(
        outcome.data["questions"]
    )
    return outcome


def _sanitize_clarify_question(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind not in QUESTION_KINDS:
        return None
    question_id = str(raw.get("id") or "").strip()
    question_prompt = str(raw.get("prompt") or "").strip()
    if not question_id or not question_prompt:
        return None

    options: list[dict[str, str]] = []
    if kind in ("single_choice", "multi_choice"):
        raw_options = raw.get("options")
        if isinstance(raw_options, list):
            for option in raw_options[:MAX_CLARIFY_OPTIONS]:
                if not isinstance(option, dict):
                    continue
                value = str(option.get("value") or "").strip()
                label = str(option.get("label") or "").strip()
                if value and label:
                    options.append({"value": value[:64], "label": label[:64]})
        if not options:
            return None

    return {
        "id": question_id[:64],
        "kind": kind,
        "prompt": question_prompt[:200],
        "options": options,
        "required": bool(raw.get("required")),
    }
