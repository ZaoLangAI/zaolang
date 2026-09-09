"""Canvas planner: turns a goal plus the cards around it into generation tasks.

The Agent never talks to a provider. It emits `GenerationParams`-shaped tasks,
and `domain/canvas/agent_service.py` submits each through the ordinary
`jobs_service.submit`, so credits, routing, moderation and skill context all
still apply exactly as they do for a hand-driven studio request.

Three things it is deliberately not allowed to decide:

* **The model.** `forced_model` is not in the output schema at all. Routing
  exists to make cost and availability deterministic; letting a language model
  pick the endpoint gives that up for nothing.
* **A higher quality tier.** The tier the user chose is a ceiling — the planner
  may lower it for a cheap draft, never raise it. Otherwise "make me a few
  options" quietly becomes a cinematic-tier bill.
* **How many tasks to run.** Capped by the caller, because every task is real
  money.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import JSON_INSTRUCTION, AgentOutcome, run_agent_stream
from app.llm.client import StreamChunk
from app.llm.normalize import extract_json
from app.models.enums import AgentName

CANVAS_PLAN_SLOT = "canvas_generate_plan"

# The operations a card can be produced by. Audio and video analysis are
# excluded on purpose: neither yields something the canvas renders as a card.
PLANNABLE_OPERATIONS = (
    "text_to_image",
    "image_to_image",
    "text_to_video",
    "image_to_video",
)

SYSTEM_PROMPT = f"""你是造浪平台无限画布上的创作助手。用户选中了画布上的一张卡片，
你会看到这张卡片以及顺着连线指向它的上游卡片。请据此规划要生成什么。

规划原则：
- 只规划用户目标真正需要的任务。宁可少而准，不要凑数——每个任务都会真实扣除用户积分。
- 上游的图片卡片是参考图。要用到某张参考图时，把它的 asset_id 放进
  reference_asset_ids，并选择 image_to_image 或 image_to_video。
- 只能引用上下文里真实出现过的 asset_id。绝对不要编造 id。
- 提示词要具体、可执行、以画面为中心：写清主体、动作、环境、光线、镜头与风格。
  不要写"高质量""4K""杰作"这类无信息量的堆砌词。
- 上游若已有提示词卡片或分镜文案，把它当作作者意图来延续，不要另起炉灶。
- negative_prompt 只在确有需要排除的东西时才写。

可用 operation：{", ".join(PLANNABLE_OPERATIONS)}
- 无参考图、从文字出发做图 → text_to_image
- 有参考图、要在其基础上改 → image_to_image
- 无参考图、从文字出发做视频 → text_to_video
- 有参考图、让静帧动起来 → image_to_video
视频任务必须给 duration_seconds（整数秒，一般 5 或 8）。

不要输出 model、forced_model 或任何指定供应商的字段——路由由平台决定。
不要提高画质档位：quality_tier 只能是 preview 或 standard，留空表示沿用用户的选择。

{JSON_INSTRUCTION}
格式：{{"summary": string, "tasks": [{{"operation": string, "prompt": string,
"negative_prompt": string, "aspect_ratio": string, "duration_seconds": number,
"reference_asset_ids": [string], "quality_tier": string}}]}}"""

# An empty plan.
#
# The direct analogue of `quality.py`'s "a broken evaluator defaults to pass so
# it cannot burn the user's credits": here a broken planner generates *nothing*
# rather than a plausible-looking task the user would be charged for. The run
# fails visibly and costs zero.
FALLBACK: dict[str, Any] = {"summary": "", "tasks": []}

MAX_TOKENS = 4096
TEMPERATURE = 0.6


def stream_plan_canvas(
    session: Session,
    *,
    user_id: str,
    goal: str,
    context: dict[str, Any],
    max_tasks: int,
    quality_tier: str,
) -> tuple[Iterator[StreamChunk], Callable[[Session | None], AgentOutcome]]:
    """Streaming plan. Returns `(chunks, finalize)`.

    The caller must drain `chunks` before calling `finalize()`, and is
    responsible for sanitising the result — see
    `agent_service._sanitise_plan`, which is where the guardrails in this
    module's docstring are actually enforced. Stating them in the prompt makes
    the model cooperate; enforcing them in code is what makes them true.
    """
    user_prompt = json.dumps(
        {
            "goal": goal,
            "max_tasks": max_tasks,
            "quality_tier_ceiling": quality_tier,
            "context": context,
        },
        ensure_ascii=False,
    )
    chunks, finalize = run_agent_stream(
        session,
        agent_name=AgentName.CANVAS_PLANNER,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        user_id=user_id,
        slot=CANVAS_PLAN_SLOT,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        expect_json=True,
    )

    def finish(persist_session: Session | None = None) -> AgentOutcome:
        """Parse the streamed text into the shape callers expect.

        `run_agent_stream` hands back raw text, not parsed data — the caller
        owns the schema. Unparseable output is `degraded` with the empty
        `FALLBACK`, so a model that returns prose instead of JSON generates
        nothing rather than something arbitrary.
        """
        stream = finalize(persist_session)
        parsed = extract_json(stream.raw_text)
        return AgentOutcome(
            data=dict(parsed) if parsed is not None else dict(FALLBACK),
            raw_text=stream.raw_text,
            degraded=parsed is None or stream.degraded,
            model=stream.model,
            agent_run_id=stream.agent_run_id,
            thinking=stream.thinking,
        )

    return chunks, finish
