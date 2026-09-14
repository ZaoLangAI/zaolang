"""The cross-job media circuit breaker (`app.providers.media_breaker`)."""

from __future__ import annotations

import pytest
import redis
from sqlalchemy.orm import Session

from app.agents import router
from app.api.rate_limit import get_redis
from app.models.enums import Operation, QualityTier
from app.providers import media_breaker


def _trip(provider: str) -> None:
    for _ in range(media_breaker.FAILURE_THRESHOLD):
        media_breaker.record_outcome(
            provider, success=False, failure_code="PROVIDER_TEMPORARY_FAILURE"
        )


def _end_cooldown(provider: str) -> None:
    """Simulates the cooldown elapsing without sleeping through it."""
    get_redis().delete(f"{media_breaker.KEY_PREFIX}{provider}:open")


def test_a_route_trips_only_after_the_threshold() -> None:
    provider = "ep-a:image"
    for _ in range(media_breaker.FAILURE_THRESHOLD - 1):
        media_breaker.record_outcome(provider, success=False, failure_code="PROVIDER_TASK_FAILED")
    assert media_breaker.is_open(provider) is False

    media_breaker.record_outcome(provider, success=False, failure_code="PROVIDER_TIMEOUT")
    assert media_breaker.is_open(provider) is True
    assert media_breaker.open_routes_for_endpoint("ep-a") == ["ep-a:image"]


def test_input_and_quality_failures_never_trip_it() -> None:
    provider = "ep-b:image"
    for code in ("MISSING_REFERENCE", "QUALITY_REJECTED", "CANCELLED"):
        for _ in range(media_breaker.FAILURE_THRESHOLD):
            media_breaker.record_outcome(provider, success=False, failure_code=code)
    assert media_breaker.is_open(provider) is False


def test_a_success_resets_the_failure_streak() -> None:
    provider = "ep-c:image"
    for _ in range(media_breaker.FAILURE_THRESHOLD - 1):
        media_breaker.record_outcome(provider, success=False)
    media_breaker.record_outcome(provider, success=True)
    media_breaker.record_outcome(provider, success=False)
    assert media_breaker.is_open(provider) is False


def test_half_open_lets_exactly_one_probe_through_and_a_success_closes_it() -> None:
    provider = "ep-d:video"
    _trip(provider)
    _end_cooldown(provider)

    assert media_breaker.is_open(provider) is False  # the probe
    assert media_breaker.is_open(provider) is True  # everyone else waits for it

    media_breaker.record_outcome(provider, success=True)
    assert media_breaker.is_open(provider) is False
    assert media_breaker.is_open(provider) is False


def test_a_failed_probe_reopens_the_route_at_once() -> None:
    provider = "ep-e:video"
    _trip(provider)
    _end_cooldown(provider)
    assert media_breaker.is_open(provider) is False  # the probe

    media_breaker.record_outcome(provider, success=False, failure_code="PROVIDER_TASK_FAILED")
    assert media_breaker.is_open(provider) is True


def test_a_redis_outage_keeps_every_route_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
                raise redis.RedisError("down")

            return fail

    monkeypatch.setattr(media_breaker, "get_redis", lambda: _Broken())
    assert media_breaker.is_open("ep-f:image") is False
    media_breaker.record_outcome("ep-f:image", success=False)  # must not raise
    assert media_breaker.open_routes_for_endpoint("ep-f") == []


def test_route_filters_an_open_route_and_records_why(db: Session, fake_media_catalog: None) -> None:
    catalog = router.build_catalog(db)
    image_routes = sorted(
        name
        for name, capability in catalog.items()
        if Operation.TEXT_TO_IMAGE.value in capability.operations
    )
    assert image_routes, "the fake catalogue must offer a text-to-image route"
    broken = image_routes[0]
    _trip(broken)

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE.value, quality_tier=QualityTier.STANDARD.value
    )
    candidate = next(item for item in decision.candidates if item.provider == broken)
    assert candidate.eligible is False
    assert candidate.filter_reason == "provider_circuit_open"
    assert decision.selected is None or decision.selected.provider != broken
