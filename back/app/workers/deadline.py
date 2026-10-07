"""The running Celery task's own soft time limit, readable from deep inside
the pipeline.

A node that can choose to skip optional work (consistency scoring, P3-3)
checks `seconds_left()` before starting it, rather than letting the task's
`SoftTimeLimitExceeded` land in the middle of a write-back. Outside a
worker task — the API, tests, an inline pipeline run — there is no
deadline and `seconds_left()` is `None`.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_deadline: ContextVar[float | None] = ContextVar("task_deadline", default=None)


@contextmanager
def task_deadline(soft_time_limit: float | None) -> Iterator[None]:
    """Sets the deadline `soft_time_limit` seconds from now for the block."""
    token = _deadline.set(
        time.monotonic() + soft_time_limit if soft_time_limit and soft_time_limit > 0 else None
    )
    try:
        yield
    finally:
        _deadline.reset(token)


def seconds_left() -> float | None:
    deadline = _deadline.get()
    return None if deadline is None else deadline - time.monotonic()
