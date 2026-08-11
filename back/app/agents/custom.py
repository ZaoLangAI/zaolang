"""A generic judgment agent: whatever role an operator created in the console.

The five built-in roles each have a module here because each one's output
means something specific to the code that reads it — a safety verdict vetoes,
a quality verdict spends a retry. An operator-created judgment role has no
such contract: the `custom_agent` workflow node runs it, parks its structured
output in the workflow state under a key the node names, and lets a
downstream node read it. Nothing here settles credits, transitions a job, or
overrides another agent, which is why a role can be added without a code
review while the five built-ins' effects cannot.

The prompt comes from whatever the operator published for the agent; the
constant below is only the empty-database fallback.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.agents.slots import DEFAULT_SLOT

SYSTEM_PROMPT = f"""你是造浪平台的一个自定义判断智能体。请依据管理员发布的指令，
对输入内容做出结构化判断。若管理员尚未发布提示词，就只做一次中立的内容归纳。

{JSON_INSTRUCTION}
格式：{{"verdict": string, "confidence": number, "notes": string}}"""

# Neutral by construction: a custom role has no defined effect on the job, so
# an unavailable model must produce something a downstream node can read
# without it looking like a real judgement.
FALLBACK: dict[str, Any] = {
    "verdict": "unknown",
    "confidence": 0.0,
    "notes": "agent_unavailable",
}


def judge(
    session: Session,
    *,
    role: str,
    payload: dict[str, Any],
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    slot: str = DEFAULT_SLOT,
) -> AgentOutcome:
    return run_agent(
        session,
        agent_name=role,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
        slot=slot,
    )
