"""The declared shape of the generation workflow.

`app.workers.pipeline` is the executable version; this module is the
machine-readable description of it. The ops console renders the timeline from
here, and a test asserts the two agree, so a step added to the pipeline without
being declared is caught rather than silently missing from every replay view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.enums import JobEventType


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    key: str
    label: str
    event_type: JobEventType
    # What the user sees on the progress bar when this step begins.
    progress: int
    # True when reaching this step can end the job without the later ones.
    terminal_on_failure: bool = False
    agent: str | None = None


GENERATION_STEPS: tuple[WorkflowStep, ...] = (
    WorkflowStep(
        key="safety",
        label="安全检查",
        event_type=JobEventType.SAFETY,
        progress=8,
        terminal_on_failure=True,
        agent="safety",
    ),
    WorkflowStep(
        key="planning",
        label="规划生成方案",
        event_type=JobEventType.PLANNING,
        progress=16,
        agent="planner",
    ),
    WorkflowStep(
        key="routing",
        label="选择生成路线",
        event_type=JobEventType.ROUTING,
        progress=24,
        terminal_on_failure=True,
    ),
    WorkflowStep(
        key="generating",
        label="生成中",
        event_type=JobEventType.GENERATING,
        progress=40,
    ),
    WorkflowStep(
        key="quality_check",
        label="质量校验",
        event_type=JobEventType.QUALITY_CHECK,
        progress=78,
        agent="quality",
    ),
    WorkflowStep(
        key="succeeded",
        label="完成结算",
        event_type=JobEventType.SUCCEEDED,
        progress=100,
    ),
)


def describe_workflow() -> dict[str, Any]:
    """Serialisable description for the ops console timeline."""
    return {
        "name": "generation",
        "description": (
            "固定顺序执行，每一步都写 JobEvent，预扣积分最终只会 capture 一次或 release 一次。"
        ),
        "steps": [
            {
                "key": step.key,
                "label": step.label,
                "event_type": step.event_type.value,
                "progress": step.progress,
                "agent": step.agent,
                "terminal_on_failure": step.terminal_on_failure,
            }
            for step in GENERATION_STEPS
        ],
    }
