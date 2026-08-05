"""LLM gateway: mode selection, degradation and AgentRun bookkeeping."""

from __future__ import annotations

import pytest
from openai import APITimeoutError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import base as agents_base
from app.config import get_settings
from app.domain.errors import ProviderTemporaryFailure
from app.llm import client as llm_client
from app.llm.stub import stub_completion
from app.models import AgentRun, User
from app.models.enums import AgentRunStatus


@pytest.fixture
def force_mode(monkeypatch):  # type: ignore[no-untyped-def]
    """Overrides the effective mode without touching the cached settings object."""

    def _apply(mode: str, api_key: str = "test-key") -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "llm_mode", mode, raising=False)
        monkeypatch.setattr(settings, "llm_api_key", api_key, raising=False)

    return _apply


def _explode(*_args, **_kwargs):  # type: ignore[no-untyped-def]
    raise APITimeoutError(request=None)  # type: ignore[arg-type]


def test_stub_mode_never_calls_the_gateway(db: Session, monkeypatch, force_mode) -> None:
    force_mode("stub", api_key="")
    monkeypatch.setattr(llm_client, "_call_gateway", _explode)

    result = llm_client.complete(
        session=db,
        agent_name="safety",
        model="doubao-seed-2-1-pro",
        messages=[{"role": "user", "content": "海边的黄昏"}],
    )
    assert result.mode == "stub"
    assert result.degraded is False
    assert result.response.data is not None


def test_stub_output_is_deterministic() -> None:
    """CI depends on this: the same prompt must always produce the same verdict."""
    messages = [{"role": "user", "content": "同一个提示词"}]
    first = stub_completion(agent_name="safety", messages=messages, model="doubao-seed-2-1-pro")
    second = stub_completion(agent_name="safety", messages=messages, model="doubao-seed-2-1-pro")
    assert first.data == second.data


def test_auto_mode_degrades_to_the_stub_on_a_gateway_failure(
    db: Session, monkeypatch, force_mode
) -> None:
    force_mode("auto")
    monkeypatch.setattr(llm_client, "_call_gateway", _explode)

    result = llm_client.complete(
        session=db,
        agent_name="planner",
        model="kimi-k3",
        messages=[{"role": "user", "content": "x"}],
    )
    assert result.degraded is True
    assert result.degrade_reason == "APITimeoutError"
    assert result.response.data is not None


def test_strict_mode_surfaces_the_failure_instead_of_faking_success(
    db: Session, monkeypatch, force_mode
) -> None:
    """Silently returning stub content when the caller demanded the real gateway
    would hide an outage."""
    force_mode("openai_compatible")
    monkeypatch.setattr(llm_client, "_call_gateway", _explode)

    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="kimi-k3",
            messages=[{"role": "user", "content": "x"}],
        )


def test_auto_mode_without_a_key_resolves_to_stub(force_mode) -> None:
    force_mode("auto", api_key="")
    assert get_settings().effective_llm_mode == "stub"


def test_every_agent_call_is_recorded(db: Session, author: User) -> None:
    outcome = agents_base.run_agent(
        db,
        agent_name="copy",
        system_prompt="你是文案助手。",
        user_prompt="给这张海边照片起个标题。",
        fallback={"titles": []},
        user_id=author.id,
    )

    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.agent_name == "copy"
    assert run.user_id == author.id
    assert run.latency_ms >= 0


def test_an_unparseable_response_falls_back_without_losing_the_record(
    db: Session, author: User, monkeypatch
) -> None:
    """The fallback must be recorded as a failure, otherwise degradation is
    invisible in the ops console."""

    class _Unparseable:
        data = None
        text = "抱歉，我无法回答。"
        model = "kimi-k3"
        prompt_tokens = 10
        completion_tokens = 5
        truncated = False

    monkeypatch.setattr(
        llm_client,
        "complete",
        lambda **_: llm_client.LlmCallResult(
            response=_Unparseable(),  # type: ignore[arg-type]
            mode="openai_compatible",
            degraded=False,
            degrade_reason=None,
            latency_ms=12,
        ),
    )

    outcome = agents_base.run_agent(
        db,
        agent_name="quality",
        system_prompt="评估质量。",
        user_prompt="这张图怎么样？",
        fallback={"verdict": "needs_review"},
        user_id=author.id,
    )

    assert outcome.data == {"verdict": "needs_review"}
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.status == AgentRunStatus.FAILED
    assert run.degrade_reason == "json_parse_failed"


def test_degraded_runs_are_queryable_for_the_ops_console(
    db: Session, author: User, monkeypatch, force_mode
) -> None:
    force_mode("auto")
    monkeypatch.setattr(llm_client, "_call_gateway", _explode)

    agents_base.run_agent(
        db,
        agent_name="planner",
        system_prompt="制定计划。",
        user_prompt="海边日落",
        fallback={"steps": []},
        user_id=author.id,
    )

    degraded = list(db.scalars(select(AgentRun).where(AgentRun.degraded.is_(True))))
    assert len(degraded) == 1
    assert degraded[0].degrade_reason == "APITimeoutError"
