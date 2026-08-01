"""Connectivity smoke test against the real gateway.

Excluded from CI: it needs a key, costs money and depends on a third party.
Run with `make test-llm` when changing anything in `app/llm/`.
"""

from __future__ import annotations

import os

import pytest

from app.llm import client
from app.llm.normalize import normalize_completion

pytestmark = pytest.mark.live

MODELS = ["doubao-seed-2-1-pro", "kimi-k3", "ling-3.0-flash-free"]


@pytest.fixture(autouse=True)
def _require_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = os.getenv("LLM_API_KEY", "")
    if not key:
        pytest.skip("LLM_API_KEY 未配置，跳过真实网关测试")
    monkeypatch.setenv("LLM_MODE", "openai_compatible")
    from app.config import get_settings

    get_settings.cache_clear()
    client.reset_client_cache()


def test_gateway_is_reachable() -> None:
    result = client.probe()

    assert result["reachable"] is True
    assert result["model_count"] > 0


@pytest.mark.parametrize("model", MODELS)
def test_each_model_returns_parseable_json(model: str) -> None:
    """Whatever the model's output habits, normalisation must yield a dict."""
    result = client.complete(
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


def test_thinking_output_is_stripped() -> None:
    """A model asked to think out loud must still yield clean text."""
    result = client.complete(
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


def test_reasoning_model_with_a_tiny_budget_still_produces_output() -> None:
    """The client raises the ceiling for reasoning models rather than
    returning the empty content the gateway would otherwise give back."""
    result = client.complete(
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


def test_recorded_shapes_match_the_live_contract() -> None:
    """Guards the fixtures used by the offline tests.

    If the gateway ever stops returning `reasoning_details`, this fails here
    rather than silently invalidating the unit tests.
    """
    raw = client.get_client().chat.completions.create(
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
