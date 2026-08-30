"""`app.llm.failover.lease`: the concurrency counter Redis key.

Narrow unit tests against the counter itself (not the full endpoint-selection
machinery covered by `test_llm_gateway_failover.py`), since the bug this
guards against is purely about what `lease()` leaves behind in Redis.
"""

from __future__ import annotations

from app.api.rate_limit import get_redis
from app.llm import failover


def _key(endpoint_id: str) -> str:
    return f"{failover._CONCURRENCY_PREFIX}{endpoint_id}"


def test_a_normal_lease_decrements_back_to_zero() -> None:
    endpoint_id = "test:lease:normal"
    client = get_redis()
    client.delete(_key(endpoint_id))
    try:
        with failover.lease(endpoint_id):
            assert failover.current_concurrency(client, endpoint_id) == 1
        assert failover.current_concurrency(client, endpoint_id) == 0
    finally:
        client.delete(_key(endpoint_id))


def test_a_decrement_that_goes_negative_deletes_the_key_instead_of_pinning_it_at_zero() -> None:
    """Reproduces the counter's "< 0" recovery branch: a start value already
    below the balanced range (e.g. from a lease acquired around a Redis
    blip). The old code path (`client.set(key, 0)`) would leave a permanent
    key with no TTL; deleting it instead relies on `current_concurrency`
    already treating a missing key as 0, and never outlives the lease."""
    endpoint_id = "test:lease:negative"
    client = get_redis()
    key = _key(endpoint_id)
    client.set(key, -1)
    try:
        with failover.lease(endpoint_id):
            pass
        assert client.exists(key) == 0
        assert failover.current_concurrency(client, endpoint_id) == 0
    finally:
        client.delete(key)
