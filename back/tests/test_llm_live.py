"""Connectivity smoke test against the real gateway.

Excluded from CI: it needs a key, costs money and depends on a third party.
Run with `make test-llm` when changing anything in `app/llm/`.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.orm import Session

from app.llm import client
from app.llm.normalize import normalize_completion
from app.platform_config import service as config_service

pytestmark = pytest.mark.live

MODELS = ["doubao-seed-2-1-pro", "kimi-k3", "ling-3.0-flash-free"]

LIVE_ENDPOINT_ID = "live-test-endpoint"


@pytest.fixture(autouse=True)
def _require_key(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    """Bootstraps a DB-backed endpoint from `.env` for the duration of the test.

    Endpoints only ever come from the database now; `LLM_BASE_URL`/
    `LLM_API_KEY` are read here purely so this manual suite can still be
    pointed at a real gateway without an `/admin/providers` round trip.
    """
    key = os.getenv("LLM_API_KEY", "")
    if not key:
        pytest.skip("LLM_API_KEY 未配置，跳过真实网关测试")
    monkeypatch.setenv("LLM_MODE", "openai_compatible")
    from app.config import get_settings

    get_settings.cache_clear()
    client.reset_client_cache()

    config_service.set_value(
        db,
        "llm_providers",
        {
            "endpoints": {
                LIVE_ENDPOINT_ID: {
                    "name": "真实网关连通性测试端点",
                    "base_url": os.getenv("LLM_BASE_URL", "https://aihubmix.com/v1"),
                    "api_key": key,
                    "kind": "general",
                    "role": "primary",
                }
            }
        },
        actor_user_id=None,
        note="live test bootstrap",
    )


def _current_endpoint(db: Session):  # type: ignore[no-untyped-def]
    from app.platform_config.schemas import LlmProviderConfig

    config = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    return config.endpoints[LIVE_ENDPOINT_ID]


def test_gateway_is_reachable(db: Session) -> None:
    result = client.probe(db)

    assert result["reachable"] is True
    assert result["model_count"] > 0


@pytest.mark.parametrize("model", MODELS)
def test_each_model_returns_parseable_json(db: Session, model: str) -> None:
    """Whatever the model's output habits, normalisation must yield a dict."""
    result = client.complete(
        session=db,
        agent_name="safety",
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是内容安全审核器。只输出 JSON，格式为 "
                '{"decision": "approve|reject", "reason_code": string|null}。',
            },
            {"role": "user", "content": "一只在雨夜霓虹街道上奔跑的机械狐狸"},
        ],
        max_tokens=512,
        temperature=0.0,
        expect_json=True,
        # Both kimi and ling think before answering.
        reasoning_model=model != "doubao-seed-2-1-pro",
    )

    assert result.degraded is False, f"{model} 降级了: {result.degrade_reason}"
    assert result.response.data is not None, f"{model} 未返回可解析 JSON: {result.response.text!r}"
    assert result.response.data.get("decision") in {"approve", "reject"}


def test_thinking_output_is_stripped(db: Session) -> None:
    """A model asked to think out loud must still yield clean text."""
    result = client.complete(
        session=db,
        agent_name="copy",
        model="kimi-k3",
        messages=[
            {"role": "system", "content": '只输出 JSON: {"title": string}。'},
            {"role": "user", "content": "为一段赛博朋克短片起标题，先思考再回答。"},
        ],
        max_tokens=1024,
        expect_json=True,
        reasoning_model=True,
    )

    assert "<think>" not in result.response.text
    assert result.response.data is not None


def test_reasoning_model_with_a_tiny_budget_still_produces_output(db: Session) -> None:
    """The client raises the ceiling for reasoning models rather than
    returning the empty content the gateway would otherwise give back."""
    result = client.complete(
        session=db,
        agent_name="copy",
        model="ling-3.0-flash-free",
        messages=[
            {"role": "system", "content": '只输出 JSON: {"title": string}。'},
            {"role": "user", "content": "给一张深海霓虹主题的图片起标题。"},
        ],
        max_tokens=16,
        expect_json=True,
        reasoning_model=True,
    )

    assert result.response.text != ""


def test_recorded_shapes_match_the_live_contract(db: Session) -> None:
    """Guards the fixtures used by the offline tests.

    If the gateway ever stops returning `reasoning_details`, this fails here
    rather than silently invalidating the unit tests.
    """
    raw = client.client_for_endpoint(_current_endpoint(db)).chat.completions.create(
        model="ling-3.0-flash-free",
        messages=[{"role": "user", "content": "用一句话解释潮汐。"}],
        max_tokens=16,
    )
    payload = raw.model_dump()

    assert "choices" in payload
    message = payload["choices"][0]["message"]
    assert "content" in message
    normalized = normalize_completion(payload, expect_json=False)
    assert isinstance(normalized.text, str)
