"""Quality agent: decides whether an output is good enough to keep."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent
from app.models.enums import AgentName

SYSTEM_PROMPT = f"""你是造浪平台的质量评估器。评估生成结果是否达到可交付标准。

重要：`output` 字段按系统设计只包含技术元数据（宽高、供应商、是否为部分结果
partial_output、上游状态 upstream_status 等），绝不会附带图像/视频/音频的实际内容、
截图或预览——这是正常情况，不代表生成失败或内容缺失。**"看不到实际媒体内容"本身
永远不能作为判定 fail 的理由**，只能依据这些元数据是否显示出明确异常（例如
partial_output 为 true、upstream_status 异常）以及 prompt 本身的合理性来评估。

不要因为宽高缺失、或提示词里的时长/规格表述（例如分镜文案中的「0—3秒」）
与交货不一致而判定 fail。视频按表单参数生成，分镜散文中的秒数不是交货规格；
`upstream_status` 为成功且并非 partial_output 时，时长不是异常。

评分维度均为 0 到 1 的小数：
- prompt_alignment：与用户描述的一致程度
- technical_quality：清晰度、伪影、结构合理性
- aesthetic：构图与视觉表现

只有在元数据明确显示异常时才判定 fail 并建议重试；重试会额外消耗用户积分，不要因为
轻微瑕疵、或仅仅因为看不到实际媒体内容就要求重试。

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

# The vision consistency judge (slot `consistency`, P3-1). Only the general
# instructions live here: the card kind's dimensions, what to ignore and the
# exact JSON keys come in each call's user message
# (`app.domain.image_assets.consistency`), and Python computes the weighted
# total — a model-reported overall score is never trusted.
CONSISTENCY_SYSTEM_PROMPT = f"""你是造浪平台的视觉一致性评审。每次会收到两张图：
图 1 是角色/场景/道具卡的锚点（已定稿的标准形象），图 2 是新生成的待评图。
你的任务是判断图 2 与图 1 是否是同一个角色/同一个场景/同一件道具，并按用户消息
列出的评分维度逐项打分。

规则：
- 每个维度给 0 到 100 的整数：90 以上几乎一致；70 左右可辨认但有明显偏差；
  50 以下已像另一个角色/场景/道具。
- 只评一致性，不评美观、清晰度或构图好坏。
- 用户消息里"不比较"的项目一律忽略，不能因此扣分（例如表情、姿态、机位、背景，
  或本次有意改变的光照、天气、状态、年代、服装）。
- 两张图画风不同（写实 / 动漫 / 3D 等）时，只在"画风与媒介"一类维度里扣分，
  其他维度仍按可辨认的特征比较。
- 必须为用户消息列出的每一个维度键打分，不要增加或改名。
- issues 写具体差异（例如"脸型偏长""发色由黑变棕"），最多 5 条，每条不超过 30 字；
  没有明显差异时给空数组。
- notes 用一两句话概括判断依据。

{JSON_INSTRUCTION}
格式：{{"dimensions": {{"<维度键>": integer}}, "issues": [string], "notes": string}}"""


def evaluate(
    session: Session,
    *,
    prompt: str,
    output_summary: dict[str, Any],
    attempt_number: int,
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AgentOutcome:
    outcome = run_agent(
        session,
        agent_name=AgentName.QUALITY,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps({"prompt": prompt, "output": output_summary}, ensure_ascii=False),
        fallback=FALLBACK,
        job_id=job_id,
        user_id=user_id,
        agent_id=agent_id,
    )

    # Retrying is capped regardless of the verdict so a persistently unhappy
    # evaluator cannot loop the job.
    if attempt_number > MAX_QUALITY_RETRIES:
        outcome.data["should_retry"] = False
    return outcome
