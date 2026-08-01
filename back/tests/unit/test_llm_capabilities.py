"""Model capability negotiation.

The error strings below are copied verbatim from live gateway rejections.
"""

from __future__ import annotations

import pytest

from app.llm import capabilities


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    capabilities.reset()


def test_models_start_out_assumed_capable() -> None:
    caps = capabilities.get("doubao-seed-2-1-pro")

    assert caps.supports_response_format is True
    assert caps.supports_temperature is True


def test_structured_output_rejection_disables_response_format() -> None:
    message = (
        "Error code: 400 - Provider returned error | upstream: provider=Novita, "
        'raw={"code":400,"reason":"INVALID_REQUEST_BODY","message":"model: '
        'inclusionai/ling-3.0-flash does not support feature: structured-outputs"}'
    )

    learned = capabilities.learn_from_error("ling-3.0-flash-free", message)

    assert learned is True
    assert capabilities.get("ling-3.0-flash-free").supports_response_format is False


def test_temperature_rejection_records_the_forced_value() -> None:
    message = "Error code: 400 - invalid temperature: only 1 is allowed for this model"

    learned = capabilities.learn_from_error("kimi-k3", message)

    assert learned is True
    caps = capabilities.get("kimi-k3")
    assert caps.supports_temperature is False
    assert caps.forced_temperature == 1.0


def test_unrelated_error_teaches_nothing() -> None:
    """A quota or auth failure must not silently degrade the request shape."""
    learned = capabilities.learn_from_error("kimi-k3", "Error code: 429 - rate limit exceeded")

    assert learned is False
    assert capabilities.get("kimi-k3").supports_response_format is True


def test_repeated_rejection_stops_the_retry_loop() -> None:
    """The second identical error yields no new knowledge, so the caller stops
    instead of retrying forever."""
    message = "does not support feature: structured-outputs"

    assert capabilities.learn_from_error("m", message) is True
    assert capabilities.learn_from_error("m", message) is False


def test_max_tokens_rejection_switches_the_parameter_name() -> None:
    message = "Unsupported parameter: 'max_tokens' is not supported, use 'max_completion_tokens'"

    capabilities.learn_from_error("some-model", message)

    assert capabilities.get("some-model").uses_max_completion_tokens is True


def test_snapshot_exposes_learned_state_for_the_console() -> None:
    capabilities.learn_from_error("kimi-k3", "invalid temperature: only 1 is allowed")

    assert "kimi-k3" in capabilities.snapshot()
