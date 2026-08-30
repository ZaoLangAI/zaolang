"""Per-user concurrent-SSE-stream cap.

The backing store is a Redis sorted set scored by last-refresh time, so these
tests check both the cap itself and the self-healing (stale members age out
without a decrement-on-disconnect) that makes the cap safe against a killed
worker.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import sse_quota
from app.domain.credits import service as credits_service
from app.domain.errors import RateLimited
from app.domain.jobs import service as jobs_service
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import Operation, QualityTier
from app.workers import pipeline
from tests.conftest import auth_header


def _reset(scope: str, user_id: str) -> None:
    sse_quota.get_redis().delete(sse_quota._key(scope, user_id))


def test_reserving_up_to_the_cap_succeeds() -> None:
    _reset("test", "user-a")
    try:
        members = [
            sse_quota.reserve("test", "user-a")
            for _ in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER)
        ]
        assert len(set(members)) == sse_quota.MAX_CONCURRENT_STREAMS_PER_USER
    finally:
        _reset("test", "user-a")


def test_reserving_past_the_cap_raises_with_a_retry_hint() -> None:
    _reset("test", "user-b")
    try:
        for _ in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER):
            sse_quota.reserve("test", "user-b")

        with pytest.raises(RateLimited) as excinfo:
            sse_quota.reserve("test", "user-b")
        assert excinfo.value.retry_after_seconds > 0
    finally:
        _reset("test", "user-b")


def test_releasing_a_slot_frees_it_for_a_new_reservation() -> None:
    _reset("test", "user-c")
    try:
        member = sse_quota.reserve("test", "user-c")
        for _ in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER - 1):
            sse_quota.reserve("test", "user-c")

        sse_quota.release("test", "user-c", member)
        # Freed exactly one slot — reserving one more must succeed again.
        sse_quota.reserve("test", "user-c")
    finally:
        _reset("test", "user-c")


def test_two_users_do_not_share_a_budget() -> None:
    """Otherwise one user with many tabs open would throttle everyone else."""
    _reset("test", "user-d")
    _reset("test", "user-e")
    try:
        for _ in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER):
            sse_quota.reserve("test", "user-d")
        sse_quota.reserve("test", "user-e")
    finally:
        _reset("test", "user-d")
        _reset("test", "user-e")


def test_a_stale_slot_that_stopped_refreshing_does_not_count_forever() -> None:
    """A worker that dies mid-stream never runs `release` — the slot must
    still age out on its own rather than leaking the cap permanently."""
    _reset("test", "user-f")
    try:
        import time

        client = sse_quota.get_redis()
        key = sse_quota._key("test", "user-f")
        # Backdate every member past the staleness window instead of sleeping
        # the real window away.
        stale_at = time.time() - sse_quota.STALE_AFTER_SECONDS - 1
        for i in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER):
            client.zadd(key, {f"stale-{i}": stale_at})

        # A fresh reservation prunes the stale members before counting, so
        # the cap does not stay wedged at "full" forever.
        sse_quota.reserve("test", "user-f")
        assert client.zcard(key) == 1
    finally:
        _reset("test", "user-f")


def test_touch_refreshes_a_slot_without_changing_the_count() -> None:
    _reset("test", "user-g")
    try:
        member = sse_quota.reserve("test", "user-g")
        before = sse_quota.get_redis().zcard(sse_quota._key("test", "user-g"))
        sse_quota.touch("test", "user-g", member)
        after = sse_quota.get_redis().zcard(sse_quota._key("test", "user-g"))
        assert before == after == 1
    finally:
        _reset("test", "user-g")


def test_a_redis_outage_does_not_lock_users_out_of_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability beats strictness, matching `rate_limit`'s policy."""
    import redis

    class Broken:
        def pipeline(self):
            raise redis.RedisError("down")

        def zremrangebyscore(self, *a, **k):
            raise redis.RedisError("down")

        def zcard(self, *a, **k):
            raise redis.RedisError("down")

        def zrem(self, *a, **k):
            raise redis.RedisError("down")

    monkeypatch.setattr(sse_quota, "get_redis", lambda: Broken())
    member = sse_quota.reserve("test", "user-h")
    sse_quota.touch("test", "user-h", member)
    sse_quota.release("test", "user-h", member)


def test_a_user_already_at_the_stream_cap_gets_429_from_the_job_stream(
    client: TestClient, db: Session, author: User
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "满员的连接池", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    job: GenerationJob = result.job

    _reset("job_events", author.id)
    try:
        for _ in range(sse_quota.MAX_CONCURRENT_STREAMS_PER_USER):
            sse_quota.reserve("job_events", author.id)

        response = client.get(f"/v1/generation-jobs/{job.id}/events", headers=auth_header(author))
        assert response.status_code == 429
    finally:
        _reset("job_events", author.id)
