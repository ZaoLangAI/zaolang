"""Admin connectivity probes persist only status and the public result."""

from __future__ import annotations

from app.api.schemas.admin import LlmProviderValidationResult
from app.providers import validation_jobs


def test_a_running_job_is_readable_then_completes() -> None:
    job = validation_jobs.create_running(endpoint_id="ep-a", timeout_ms=30_000)
    assert job.status == "running"
    assert job.result is None
    assert job.timeout_ms == 30_000
    assert job.validation_id.startswith("val_")

    loaded = validation_jobs.get("ep-a", job.validation_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.result is None


def test_a_completed_job_stores_the_result_without_an_api_key() -> None:
    job = validation_jobs.create_running(endpoint_id="ep-a", timeout_ms=90_000)
    result = LlmProviderValidationResult(
        endpoint_id="ep-a",
        kind="media",
        target_model="qwen-image-3.0",
        probe_type="text_to_image",
        reachable=True,
        usable=True,
        latency_ms=50625,
        provider_status_code=200,
    )
    validation_jobs.complete(job.validation_id, result)

    loaded = validation_jobs.get("ep-a", job.validation_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.result is not None
    assert loaded.result.usable is True
    assert loaded.result.target_model == "qwen-image-3.0"
    dumped = loaded.model_dump(mode="json")
    assert "api_key" not in str(dumped)


def test_a_job_is_not_visible_under_a_different_endpoint() -> None:
    job = validation_jobs.create_running(endpoint_id="ep-a", timeout_ms=30_000)
    assert validation_jobs.get("ep-b", job.validation_id) is None


def test_ttl_covers_the_endpoint_timeout_with_a_floor() -> None:
    assert validation_jobs.ttl_seconds(5_000) == 180
    assert validation_jobs.ttl_seconds(90_000) == 180
    assert validation_jobs.ttl_seconds(180_000) == 240
