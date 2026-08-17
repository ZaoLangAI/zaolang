"""`app.llm.client.complete`: failover across endpoints, the circuit breaker,
and every path that must fail loudly instead of returning fabricated output.

Every test here is marked `real_gateway_seams` to opt out of the autouse
`tests/fake_llm_gateway.py` fixture — that fake replaces `complete()` itself,
which would make these tests exercise nothing. Only the transport
(`app.llm.client._call_gateway`) is mocked, so `complete()`'s own endpoint
selection, retry, failover and circuit-breaker logic runs for real against a
real (test-only) `llm_providers` config.
"""

from __future__ import annotations

import json

import pytest
from openai import APITimeoutError
from sqlalchemy.orm import Session

from app.api.rate_limit import get_redis
from app.domain.errors import ProviderTemporaryFailure
from app.llm import client as llm_client
from app.llm import failover
from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

pytestmark = pytest.mark.real_gateway_seams


def _completion_payload(model: str, data: dict) -> dict:
    return {
        "model": model,
        "choices": [
            {"message": {"content": json.dumps(data, ensure_ascii=False)}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 3},
    }


def _always_times_out(*_args, **_kwargs):  # type: ignore[no-untyped-def]
    raise APITimeoutError(request=None)  # type: ignore[arg-type]


def _seed_endpoint(
    db: Session,
    *,
    endpoint_id: str = "test-endpoint",
    model: str = "test-llm",
    role: str = "primary",
    backup_order: int = 100,
) -> None:
    current = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    endpoints = {
        existing_id: endpoint.model_dump(mode="json")
        for existing_id, endpoint in current.endpoints.items()
    }
    endpoints[endpoint_id] = {
        "name": f"测试端点 {endpoint_id}",
        "base_url": "https://example.invalid/v1",
        "api_key": "test-key",
        "kind": "general",
        "model": model,
        "role": role,
        "backup_order": backup_order,
    }
    config_service.set_value(
        db, "llm_providers", {"endpoints": endpoints}, actor_user_id=None, note="test bootstrap"
    )


def test_an_empty_model_raises_without_calling_the_gateway(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_client, "_call_gateway", _always_times_out)

    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="",
            messages=[{"role": "user", "content": "x"}],
        )


def test_no_endpoint_configured_raises(db: Session) -> None:
    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
        )


def test_a_gateway_failure_raises_instead_of_faking_success(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently returning fabricated content when the real gateway failed
    would hide an outage from whoever is supposed to notice it."""
    _seed_endpoint(db)
    monkeypatch.setattr(llm_client, "_call_gateway", _always_times_out)

    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
        )


def test_a_successful_call_returns_the_endpoint_that_served_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, endpoint_id="only-endpoint", model="test-llm")
    monkeypatch.setattr(
        llm_client, "_call_gateway", lambda **kw: _completion_payload(kw["model"], {"ok": True})
    )

    result = llm_client.complete(
        session=db,
        agent_name="planner",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
    )

    assert result.endpoint_id == "only-endpoint"
    assert result.response.data == {"ok": True}


def test_failover_moves_to_the_backup_endpoint_on_a_primary_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, endpoint_id="primary-ep", model="primary-model", role="primary")
    _seed_endpoint(db, endpoint_id="backup-ep", model="backup-model", role="backup")

    def _call_gateway(**kwargs):  # type: ignore[no-untyped-def]
        if kwargs["model"] == "primary-model":
            raise APITimeoutError(request=None)  # type: ignore[arg-type]
        return _completion_payload(kwargs["model"], {"served_by": kwargs["model"]})

    monkeypatch.setattr(llm_client, "_call_gateway", _call_gateway)

    result = llm_client.complete(
        session=db,
        agent_name="planner",
        model="primary-model",
        messages=[{"role": "user", "content": "x"}],
    )

    assert result.endpoint_id == "backup-ep"
    assert result.response.data == {"served_by": "backup-model"}
    assert result.response.model == "backup-model"


def test_circuit_breaker_opens_after_repeated_failures_and_excludes_the_endpoint(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, endpoint_id="flaky-ep", model="test-llm")
    monkeypatch.setattr(llm_client, "_call_gateway", _always_times_out)

    for _ in range(llm_client.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        with pytest.raises(ProviderTemporaryFailure):
            llm_client.complete(
                session=db,
                agent_name="planner",
                model="test-llm",
                messages=[{"role": "user", "content": "x"}],
            )

    assert failover.is_breaker_open(get_redis(), "flaky-ep") is True

    # The breaker now excludes the endpoint entirely rather than attempting
    # (and failing) another transport call — a distinct failure mode from
    # "the gateway answered and it was an error".
    call_count = 0

    def _count_calls(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        raise APITimeoutError(request=None)  # type: ignore[arg-type]

    monkeypatch.setattr(llm_client, "_call_gateway", _count_calls)
    with pytest.raises(ProviderTemporaryFailure, match="未配置任何可用的 LLM 网关端点"):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
        )
    assert call_count == 0


def test_every_agent_call_is_recorded(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_agent` must record an `AgentRun` for a real, successful call —
    exercised here (not via the fake gateway) to prove the bookkeeping wires
    up to `complete()`'s real return shape."""
    from app.agents import base as agents_base
    from app.models import AgentRun
    from tests.llm_catalog import bind_default_agents_to_catalog

    bind_default_agents_to_catalog(db, model="test-llm", endpoint_id="agent-run-ep")

    def _call_gateway(**kwargs):  # type: ignore[no-untyped-def]
        return _completion_payload(kwargs["model"], {"titles": ["海边的黄昏"]})

    monkeypatch.setattr(llm_client, "_call_gateway", _call_gateway)
    outcome = agents_base.run_agent(
        db,
        agent_name="copy",
        system_prompt="你是文案助手。",
        user_prompt="给这张海边照片起个标题。",
        fallback={"titles": []},
        user_id=author.id,
    )

    run = db.get(AgentRun, outcome.agent_run_id)
    assert isinstance(run, AgentRun)
    assert run.agent_name == "copy"
    assert run.user_id == author.id
    assert run.status == "succeeded"
    assert run.degraded is False
    assert run.latency_ms >= 0
    assert outcome.data == {"titles": ["海边的黄昏"]}


def test_an_unparseable_response_is_recorded_as_a_failed_degraded_run(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback must be recorded as a failure, otherwise degradation is
    invisible in the ops console. This is the one remaining `degraded` cause
    now that a gateway-level failure raises instead of degrading."""
    from app.agents import base as agents_base
    from app.models import AgentRun
    from app.models.enums import AgentRunStatus

    class _Unparseable:
        data = None
        text = "抱歉，我无法回答。"
        model = "test-llm"
        prompt_tokens = 10
        completion_tokens = 5
        truncated = False

    monkeypatch.setattr(
        llm_client,
        "complete",
        lambda **_: llm_client.LlmCallResult(response=_Unparseable(), latency_ms=12),  # type: ignore[arg-type]
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
    assert run.degraded is True
    assert run.degrade_reason == "json_parse_failed"
