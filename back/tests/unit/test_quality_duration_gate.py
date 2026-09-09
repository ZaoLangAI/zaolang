"""Quality must not fail a video because the shot card mentions a duration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.agents import quality
from app.agents.base import AgentOutcome
from app.models import User
from app.models.enums import Operation
from app.providers.base import GenerationResult
from app.workflows.configs import QualityCheckConfig
from app.workflows.nodes import execute_quality_check
from app.workflows.types import WorkflowContext
from tests.factories import make_job


def test_quality_prompt_does_not_treat_duration_mismatch_as_a_fail() -> None:
    assert "时长与请求明显不符" not in quality.SYSTEM_PROMPT
    assert "分镜散文中的秒数不是交货规格" in quality.SYSTEM_PROMPT


def test_evaluate_passes_when_shot_card_duration_disagrees_with_delivery(
    db: Session,
) -> None:
    outcome = quality.evaluate(
        db,
        prompt="时长：0—3秒\n\n清晨城市街道。",
        output_summary={
            "width": 1280,
            "height": 720,
            "provider": "ep_test:text_to_video",
            "partial_output": False,
            "upstream_status": "succeeded",
        },
        attempt_number=1,
    )
    assert outcome.data["verdict"] == "pass"
    assert outcome.data["should_retry"] is False


def test_quality_check_omits_duration_ms_from_the_evaluator(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _fake_evaluate(_session: object, **kwargs: object) -> AgentOutcome:
        captured.update(kwargs)
        return AgentOutcome(
            data={
                "verdict": "pass",
                "scores": {
                    "prompt_alignment": 0.8,
                    "technical_quality": 0.8,
                    "aesthetic": 0.8,
                },
                "should_retry": False,
                "notes": "ok",
            },
            raw_text="{}",
            degraded=False,
            model="test",
            agent_run_id="agr_test",
        )

    monkeypatch.setattr("app.workflows.nodes.quality.evaluate", _fake_evaluate)

    job = make_job(db, author, operation=Operation.TEXT_TO_VIDEO)
    ctx = WorkflowContext(
        session=db,
        job=job,
        prompt="时长：0—3秒\n\n清晨城市街道。",
        params={"duration_seconds": 8},
        dry_run=True,
    )
    ctx.state["result"] = GenerationResult(
        succeeded=True,
        mime_type="video/mp4",
        width=1280,
        height=720,
        duration_ms=8000,
        metadata={"partial_output": False, "upstream_status": "succeeded"},
    )
    ctx.state["capability"] = SimpleNamespace(name="ep_test:text_to_video")

    outcome = execute_quality_check(ctx, QualityCheckConfig())
    assert outcome.port == "pass"
    summary = captured["output_summary"]
    assert isinstance(summary, dict)
    assert "duration_ms" not in summary
    assert summary["upstream_status"] == "succeeded"
    assert captured["prompt"] == ctx.prompt
