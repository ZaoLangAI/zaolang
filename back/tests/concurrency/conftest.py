"""Fixtures for tests that run real concurrent transactions.

These tests cannot use the rolled-back `db` fixture: the point is that two
transactions on two connections race each other, which is invisible inside a
single transaction. Each test therefore commits for real, and the schema is
truncated afterwards.

Two rules keep a failing race from wedging the whole suite. A worker always ends
its transaction, so a loser cannot sit on a row lock that the other workers are
waiting for; and every session gets a `lock_timeout`, so even an unforeseen
deadlock surfaces as a failed test rather than a hang.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import truncate_all

LOCK_TIMEOUT = "5s"


@pytest.fixture
def sessions(engine: Engine) -> Iterator[Callable[[], Session]]:
    """Hands out independent sessions, each on its own connection."""
    opened: list[Session] = []
    lock = threading.Lock()

    def factory() -> Session:
        session = Session(bind=engine, expire_on_commit=False)
        session.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT}'"))
        with lock:
            opened.append(session)
        return session

    try:
        yield factory
    finally:
        for session in opened:
            session.rollback()
            session.close()
        truncate_all(engine)


def race[T](work: Callable[[Session], T], make_session: Callable[[], Session]) -> Callable[[], T]:
    """Wraps one racer so it always releases its transaction.

    Without this, a racer that loses with a conflict would return while still
    holding its locks, and the winners would block until the test timed out —
    turning a clean "exactly one winner" assertion into a hang.
    """

    def run() -> T:
        session = make_session()
        try:
            result = work(session)
            session.commit()
            return result
        except BaseException:
            session.rollback()
            raise

    return run


def run_in_parallel[T](
    tasks: list[Callable[[], T]], *, timeout: float = 30.0
) -> list[T | BaseException]:
    """Runs callables at the same time and returns each outcome in order.

    Exceptions are returned rather than raised: in a race, losing with a
    conflict is the correct behaviour, so deciding what counts as a failure is
    the test's job. Threads are daemons joined with a timeout, so a genuinely
    stuck worker fails the test instead of blocking the run forever.
    """
    results: list[Any] = [None] * len(tasks)
    ready = threading.Barrier(len(tasks), timeout=timeout)

    def worker(index: int, task: Callable[[], T]) -> None:
        try:
            # Line the workers up so their statements actually interleave;
            # without this the first one often finishes before the last starts.
            ready.wait()
            results[index] = task()
        except BaseException as exc:
            results[index] = exc

    threads = [
        threading.Thread(target=worker, args=(index, task), daemon=True)
        for index, task in enumerate(tasks)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    assert not stuck, f"workers did not finish within {timeout}s: {stuck}"
    return results
