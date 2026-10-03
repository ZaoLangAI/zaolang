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

import httpx
import pytest
from openai import APITimeoutError, BadRequestError
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
    context_length: int = 0,
    max_output_tokens: int = 0,
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
        "context_length": context_length,
        "max_output_tokens": max_output_tokens,
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


def test_complete_adds_a_thinking_margin_for_reasoning_capped_by_the_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reasoning model no longer jumps straight to the endpoint's full
    declared ceiling on its first attempt — it gets the requested budget
    plus `REASONING_THINKING_MARGIN_TOKENS` of headroom, capped by that
    ceiling (here `512 + 4096 = 4608`, well under `8192`)."""
    _seed_endpoint(db, max_output_tokens=8192)
    seen: list[int] = []

    def _call_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        return _completion_payload(kwargs["model"], {"ok": True})

    monkeypatch.setattr(llm_client, "_call_gateway", _call_gateway)
    llm_client.complete(
        session=db,
        agent_name="copy",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=512,
        reasoning_model=True,
    )

    from app.platform_config.schemas import REASONING_THINKING_MARGIN_TOKENS

    assert seen == [512 + REASONING_THINKING_MARGIN_TOKENS]


def test_complete_truncation_retry_caps_at_the_endpoint_max_output(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, max_output_tokens=3000)
    seen: list[int] = []

    def _call_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        if len(seen) == 1:
            return {
                "model": kwargs["model"],
                "choices": [{"message": {"content": "not-json"}, "finish_reason": "length"}],
                "usage": {},
            }
        return _completion_payload(kwargs["model"], {"ok": True})

    monkeypatch.setattr(llm_client, "_call_gateway", _call_gateway)
    result = llm_client.complete(
        session=db,
        agent_name="copy",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=2048,
    )

    assert seen == [2048, 3000]
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


def test_a_busy_pool_waits_for_a_slot_instead_of_failing(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch can put more agent calls in flight than the pool has slots;
    the overflow waits for one to free up rather than failing the job."""
    _seed_endpoint(db, endpoint_id="busy-ep", model="test-llm")
    client = get_redis()
    client.set("llmfo:conc:busy-ep", 4)  # the default max_concurrency
    monkeypatch.setattr(
        llm_client, "_call_gateway", lambda **kw: _completion_payload(kw["model"], {"ok": True})
    )
    waits: list[float] = []

    def _finish_one_call(seconds: float) -> None:
        waits.append(seconds)
        client.decr("llmfo:conc:busy-ep")

    monkeypatch.setattr(llm_client.time, "sleep", _finish_one_call)

    result = llm_client.complete(
        session=db,
        agent_name="safety",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
    )

    assert result.endpoint_id == "busy-ep"
    low, high = llm_client.CAPACITY_POLL_SECONDS
    assert len(waits) == 1 and low <= waits[0] <= high


def test_a_pool_that_stays_busy_fails_as_busy_not_unconfigured(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, endpoint_id="busy-ep", model="test-llm")
    get_redis().set("llmfo:conc:busy-ep", 4)
    monkeypatch.setattr(llm_client, "CAPACITY_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(llm_client, "_call_gateway", _always_times_out)

    with pytest.raises(ProviderTemporaryFailure, match="LLM 网关繁忙"):
        llm_client.complete(
            session=db,
            agent_name="safety",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
        )


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


def test_stream_yields_recovered_reasoning_live_as_thinking_chunks(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """glm-5.3-flash spent ~60s thinking and left `delta.content` empty.

    Unlike the old contract, the reasoning delta *is* now yielded live as a
    `kind="thinking"` chunk — thinking is part of the visible creation
    process, not a network-layer detail the caller never sees. The
    recovered text still lands on `result.text` too, so the script parser
    can run once the stream ends.
    """
    _seed_endpoint(db)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(
            reasoning='{"title": "深海霓虹"}',
            finish_reason="stop",
        )

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
        )
    )

    assert chunks == [llm_client.StreamChunk(kind="thinking", text='{"title": "深海霓虹"}')]
    assert result.text == '{"title": "深海霓虹"}'
    assert result.thinking == '{"title": "深海霓虹"}'


def test_stream_reasoning_model_adds_a_thinking_margin_capped_by_the_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same margin-not-ceiling behavior as `complete()`, see
    `test_complete_adds_a_thinking_margin_for_reasoning_capped_by_the_ceiling`."""
    _seed_endpoint(db, max_output_tokens=8192)
    seen: list[int] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        yield llm_client.StreamDelta(content="ok", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            max_tokens=512,
            reasoning_model=True,
        )
    )

    from app.platform_config.schemas import REASONING_THINKING_MARGIN_TOKENS

    assert seen == [512 + REASONING_THINKING_MARGIN_TOKENS]
    assert result.text == "ok"


def test_stream_does_not_invent_a_reasoning_floor_when_output_is_undeclared(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)
    seen: list[int] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        yield llm_client.StreamDelta(content="ok", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            max_tokens=512,
            reasoning_model=True,
        )
    )

    assert seen == [512]


def test_stream_forwards_expect_json_to_the_gateway(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JSON-only slots (prompt polish) must be able to ask for
    `response_format` on the stream the same way `complete()` does."""
    _seed_endpoint(db)
    seen: list[bool] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(bool(kwargs.get("expect_json")))
        yield llm_client.StreamDelta(content='{"ok": true}', finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            expect_json=True,
        )
    )

    assert seen == [True]
    assert result.text == '{"ok": true}'


def test_stream_retries_once_when_empty_content_is_truncated(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)
    seen: list[int] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        if len(seen) == 1:
            yield llm_client.StreamDelta(finish_reason="length")
            return
        yield llm_client.StreamDelta(content="hello", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            max_tokens=2048,
        )
    )

    assert seen == [2048, 4096]
    assert chunks == [llm_client.StreamChunk(kind="content", text="hello")]
    assert result.text == "hello"


def test_stream_truncation_retry_caps_at_the_endpoint_max_output(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, max_output_tokens=3000)
    seen: list[int] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        if len(seen) == 1:
            yield llm_client.StreamDelta(finish_reason="length")
            return
        yield llm_client.StreamDelta(content="hello", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            max_tokens=2048,
        )
    )

    assert seen == [2048, 3000]
    assert chunks == [llm_client.StreamChunk(kind="content", text="hello")]
    assert result.text == "hello"


def test_stream_caps_output_to_remaining_context(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, context_length=1000, max_output_tokens=8000)
    seen: list[int] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs["max_tokens"])
        yield llm_client.StreamDelta(content="ok", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    # `_prompt_tokens` is len(content)//4 — 3600 chars → 900 prompt tokens,
    # leaving 100 of the 1000-token window for the completion.
    list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x" * 3600}],
            result=result,
            max_tokens=4096,
        )
    )

    assert seen == [100]


def test_stream_leaves_empty_text_after_a_failed_retry(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(finish_reason="length")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
        )
    )

    assert chunks == []
    assert result.text == ""


def test_stream_keeps_recovered_reasoning_when_finish_reason_is_length(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recovered reasoning-only payload must not be discarded by a
    truncation retry — that is the glm-5.3-flash success path. It is still
    yielded live as a `thinking` chunk on the way, same as any other
    reasoning delta."""
    _seed_endpoint(db)
    calls = 0

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        yield llm_client.StreamDelta(
            reasoning='<think>先构思</think>{"title": "深海霓虹"}',
            finish_reason="length",
        )

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
        )
    )

    assert calls == 1
    assert chunks == [
        llm_client.StreamChunk(kind="thinking", text='<think>先构思</think>{"title": "深海霓虹"}')
    ]
    assert result.text == '{"title": "深海霓虹"}'


def test_stream_drops_recovered_reasoning_that_stays_unusable_after_retry(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reasoning-only pass whose recovered text never satisfies the
    caller's `is_usable` check (e.g. a script parser finding no JSON in it)
    must not be handed back as a successful `result.text` once the one
    retry is exhausted — this is exactly the bug behind a script first
    draft's `firstDraftError` showing the model's raw, spaceless-English
    reasoning trace instead of a friendly message: both attempts here only
    ever produce free-form prose with no JSON, so `is_usable` never passes,
    and `result.text` must come back empty rather than that raw prose."""
    _seed_endpoint(db)
    calls = 0

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        yield llm_client.StreamDelta(
            reasoning="TheuserwantsashortdramascriptsetintheThree-BodyProblem universe",
            finish_reason="length",
        )

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            is_usable=lambda _text: False,
        )
    )

    assert calls == 2  # one retry spent, both attempts unusable
    assert all(chunk.kind == "thinking" for chunk in chunks)
    assert result.text == ""


def test_stream_visible_content_is_not_replaced_by_reasoning(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delta carrying both `content` and `reasoning` yields both as
    separate typed chunks (thinking first, matching processing order inside
    `_stream_complete_from_endpoints`) — `result.text` still ends up as the
    real content, never overwritten by the reasoning side-channel."""
    _seed_endpoint(db)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(content="hello", reasoning="hidden thinking")
        yield llm_client.StreamDelta(finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
        )
    )

    assert chunks == [
        llm_client.StreamChunk(kind="thinking", text="hidden thinking"),
        llm_client.StreamChunk(kind="content", text="hello"),
    ]
    assert result.text == "hello"
    assert result.thinking == "hidden thinking"


def test_stream_wall_clock_timeout_cuts_off_a_silently_stalled_stream(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that keeps the connection open but stops sending anything
    (or trickles so slowly a normal per-chunk timeout never fires) must not
    hang the request forever — `STREAM_WALL_CLOCK_TIMEOUT_SECONDS` bounds the
    whole attempt. Set to `0` here so the very first content delta already
    trips it; what was accumulated before the cutoff is still used as a
    (truncated) success rather than discarded, same as any other
    `finish_reason="length"` truncation.
    """
    _seed_endpoint(db)
    monkeypatch.setattr(llm_client, "STREAM_WALL_CLOCK_TIMEOUT_SECONDS", 0)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(content="hello")
        yield llm_client.StreamDelta(content=" there, never reached", finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
        )
    )

    assert chunks == [llm_client.StreamChunk(kind="content", text="hello")]
    assert result.text == "hello"


def test_stream_retries_thinking_only_timeout_on_the_same_endpoint(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reasoning-only wall-clock cut used to skip the one budget-expansion
    retry (`error is not None`) and raise `LLM 网关不可用: TimeoutError`
    while thinking was already on screen. The second attempt stays on the
    same endpoint — no mid-stream failover."""
    _seed_endpoint(db, endpoint_id="primary-ep", model="primary-model", role="primary")
    _seed_endpoint(db, endpoint_id="backup-ep", model="backup-model", role="backup")
    calls: list[str] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["model"])
        if len(calls) == 1:
            yield llm_client.StreamDelta(reasoning="还在拆维度")
            raise TimeoutError("stream exceeded 300s wall clock")
        yield llm_client.StreamDelta(content='{"ok": true}', finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="primary-model",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            is_usable=lambda text: "{" in text,
        )
    )

    assert calls == ["primary-model", "primary-model"]
    assert chunks == [
        llm_client.StreamChunk(kind="thinking", text="还在拆维度"),
        llm_client.StreamChunk(kind="content", text='{"ok": true}'),
    ]
    assert result.text == '{"ok": true}'


def test_stream_retries_unusable_yielded_content_on_the_same_endpoint(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A few content tokens that fail `is_usable` (truncated / decoy JSON)
    used to skip the budget-expansion retry because `yielded_from_endpoint`
    was already set. Same endpoint only — no mid-stream failover."""
    _seed_endpoint(db, endpoint_id="primary-ep", model="primary-model", role="primary")
    _seed_endpoint(db, endpoint_id="backup-ep", model="backup-model", role="backup")
    calls: list[str] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["model"])
        if len(calls) == 1:
            yield llm_client.StreamDelta(content='{"answer":"$your_answer"}', finish_reason="stop")
        else:
            yield llm_client.StreamDelta(
                content='{"prompt": "x", "detail_level": "sparse"}', finish_reason="stop"
            )

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="primary-model",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            is_usable=lambda text: "detail_level" in text,
            retry_nudge="现在只输出 JSON",
        )
    )

    assert calls == ["primary-model", "primary-model"]
    assert any(chunk.text == '{"answer":"$your_answer"}' for chunk in chunks)
    assert result.text == '{"prompt": "x", "detail_level": "sparse"}'


def test_stream_retry_appends_nudge_as_a_user_turn(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)
    seen: list[list[dict[str, str]]] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(list(kwargs["messages"]))
        yield llm_client.StreamDelta(reasoning="还在拆维度", finish_reason="length")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            is_usable=lambda _text: False,
            retry_nudge="现在只输出 JSON",
        )
    )

    assert len(seen) == 2
    assert seen[0] == [{"role": "user", "content": "x"}]
    assert seen[1][-1] == {"role": "user", "content": "现在只输出 JSON"}


def test_stream_thinking_only_timeout_after_retry_is_empty_not_an_outage(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two thinking-only timeouts must not wrap as a gateway outage — the
    caller already saw tokens and can surface `parse_ok=False` itself."""
    _seed_endpoint(db, endpoint_id="primary-ep", model="primary-model", role="primary")
    _seed_endpoint(db, endpoint_id="backup-ep", model="backup-model", role="backup")
    calls: list[str] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["model"])
        yield llm_client.StreamDelta(reasoning="还在想")
        raise TimeoutError("stream exceeded 300s wall clock")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.StreamResult()
    chunks = list(
        llm_client.stream_complete(
            session=db,
            agent_name="copy",
            model="primary-model",
            messages=[{"role": "user", "content": "x"}],
            result=result,
            is_usable=lambda _text: False,
        )
    )

    assert calls == ["primary-model", "primary-model"]
    assert all(chunk.kind == "thinking" for chunk in chunks)
    assert result.text == ""
    assert result.thinking == "还在想"


def test_complete_assembles_streamed_thinking_into_one_result(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Formal `complete()` drains `_stream_gateway` so a silent think no
    longer trips `timeout_ms` as a wall clock. The caller still gets one
    JSON blob plus the raw reasoning on `LlmCallResult.thinking`."""
    _seed_endpoint(db)
    seen: list[llm_client.StreamChunk] = []

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(reasoning="先想一步")
        yield llm_client.StreamDelta(
            content='{"ok": true}',
            finish_reason="stop",
            usage={"prompt_tokens": 4, "completion_tokens": 3},
        )

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.complete(
        session=db,
        agent_name="planner",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
        on_chunk=seen.append,
    )

    assert result.response.data == {"ok": True}
    assert result.thinking == "先想一步"
    assert seen == [
        llm_client.StreamChunk(kind="thinking", text="先想一步"),
        llm_client.StreamChunk(kind="content", text='{"ok": true}'),
    ]


def test_complete_wall_clock_timeout_fails_the_attempt(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)
    monkeypatch.setattr(llm_client, "STREAM_WALL_CLOCK_TIMEOUT_SECONDS", 0)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(reasoning="还在想")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="test-llm",
            messages=[{"role": "user", "content": "x"}],
        )


def test_complete_does_not_failover_after_handing_a_chunk_to_the_caller(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db, endpoint_id="primary-ep", model="primary-model", role="primary")
    _seed_endpoint(db, endpoint_id="backup-ep", model="backup-model", role="backup")
    models: list[str] = []
    chunks: list[llm_client.StreamChunk] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        models.append(kwargs["model"])
        yield llm_client.StreamDelta(reasoning="已经发出去了")
        raise APITimeoutError(request=None)  # type: ignore[arg-type]

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    with pytest.raises(ProviderTemporaryFailure):
        llm_client.complete(
            session=db,
            agent_name="planner",
            model="primary-model",
            messages=[{"role": "user", "content": "x"}],
            on_chunk=chunks.append,
        )

    assert models == ["primary-model"]
    assert chunks == [llm_client.StreamChunk(kind="thinking", text="已经发出去了")]


def test_call_gateway_once_stays_non_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin connectivity ping must not wait on a reasoning model's think."""
    stream_calls: list[object] = []
    create_calls: list[object] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        stream_calls.append(kwargs)
        if False:  # pragma: no cover
            yield llm_client.StreamDelta()

    def _create_completion(**kwargs):  # type: ignore[no-untyped-def]
        create_calls.append(kwargs)
        return _completion_payload(kwargs["model"], {"ok": True})

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    monkeypatch.setattr(llm_client, "_create_completion", _create_completion)
    llm_client.call_gateway_once(
        client=object(),  # type: ignore[arg-type]
        model="glm-5.3-flash",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
        temperature=0,
        expect_json=False,
    )
    assert stream_calls == []
    assert len(create_calls) == 1


def test_complete_retries_without_include_usage_when_the_gateway_rejects_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_endpoint(db)
    attempts: list[bool] = []

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        include_usage = bool(kwargs.get("include_usage", False))
        attempts.append(include_usage)
        if include_usage:
            request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            response = httpx.Response(400, request=request, text="stream_options include_usage")
            raise BadRequestError(
                "stream_options include_usage is not supported",
                response=response,
                body=None,
            )
        yield llm_client.StreamDelta(content='{"ok": true}', finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    result = llm_client.complete(
        session=db,
        agent_name="planner",
        model="test-llm",
        messages=[{"role": "user", "content": "x"}],
    )
    assert attempts == [True, False]
    assert result.response.data == {"ok": True}
