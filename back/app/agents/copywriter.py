"""Copy agent: suggests a title, description and tags for a draft."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName

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
    )

    title = str(outcome.data.get("title") or FALLBACK["title"])
    outcome.data["title"] = title[:200]
    tags = outcome.data.get("tags")
    outcome.data["tags"] = [str(t)[:64] for t in tags][:6] if isinstance(tags, list) else []
    return outcome
