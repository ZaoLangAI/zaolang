"""`app.api.v1.scripts._with_heartbeat`: the SSE heartbeat wrapper that keeps
a streamed turn's connection alive during silent gaps before the first real
chunk (or between slow-arriving ones), and the drained generator's
exceptions surfacing on the consumer side.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from app.api.v1 import scripts


def test_with_heartbeat_yields_a_heartbeat_during_a_silent_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scripts, "_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    def source() -> Iterator[str]:
        time.sleep(0.2)
        yield "a"
        yield "b"

    items = list(scripts._with_heartbeat(source()))

    heartbeats = [item for item in items if item is scripts._HEARTBEAT]
    reals = [item for item in items if item is not scripts._HEARTBEAT]
    # At least one heartbeat must land before "a" shows up — the 0.2s sleep
    # is several multiples of the 0.05s interval — but the exact count is
    # timing-dependent, so only the ordering and the real payload matter.
    assert len(heartbeats) >= 1
    assert reals == ["a", "b"]
    assert items.index(heartbeats[0]) < items.index("a")


def test_with_heartbeat_does_not_insert_heartbeats_between_fast_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scripts, "_HEARTBEAT_INTERVAL_SECONDS", 5.0)

    def source() -> Iterator[str]:
        yield "a"
        yield "b"
        yield "c"

    items = list(scripts._with_heartbeat(source()))

    assert items == ["a", "b", "c"]


def test_with_heartbeat_reraises_an_error_from_the_drained_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scripts, "_HEARTBEAT_INTERVAL_SECONDS", 5.0)

    def source() -> Iterator[str]:
        yield "a"
        raise ValueError("boom")

    it = scripts._with_heartbeat(source())
    assert next(it) == "a"
    with pytest.raises(ValueError, match="boom"):
        next(it)
