"""Quality agent: decides whether an output is good enough to keep."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName

SYSTEM_PROMPT = f"""你是造浪平台的质量评估器。评估生成结果是否达到可交付标准。
评分维度均为 0 到 1 的小数：
- prompt_alignment：与用户描述的一致程度
- technical_quality：清晰度、伪影、结构合理性
- aesthetic：构图与视觉表现

只有在明显不可用时才判定 fail 并建议重试；重试会额外消耗用户积分，不要因为轻微瑕疵就要求重试。

{JSON_INSTRUCTION}
格式：{{"verdict": "pass"|"fail", "scores": {{"prompt_alignment": number,
"technical_quality": number, "aesthetic": number}}, "should_retry": boolean, "notes": string}}"""

# Defaults to accepting: a broken evaluator must not burn the user's credits on
# repeated retries.
FALLBACK: dict[str, Any] = {
    "verdict": "pass",
    "scores": {"prompt_alignment": 0.7, "technical_quality": 0.7, "aesthetic": 0.7},
    "should_retry": False,
    "notes": "质量评估不可用，按通过处理",
}

MAX_QUALITY_RETRIES = 1


def evaluate(
    session: Session,
    *,
    prompt: str,
    output_summary: dict[str, Any],
    attempt_number: int,
    job_id: str | None = None,
    user_id: str | None = None,
) -> AgentOutcome:
    outcome = run_agent(
        session,
        agent_name=AgentName.QUALITY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt, "output": output_summary}, ensure_ascii=False),
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
    )

    # Retrying is capped regardless of the verdict so a persistently unhappy
    # evaluator cannot loop the job.
    if attempt_number > MAX_QUALITY_RETRIES:
        outcome.data["should_retry"] = False
    return outcome
