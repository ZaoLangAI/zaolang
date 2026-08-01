"""Database engine and session management."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.expression import Executable

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    # PYTEST_CURRENT_TEST is absent at import time, so tests select the URL via
    # APP_ENV rather than relying on pytest internals.
    url = settings.test_database_url if settings.app_env == "test" else settings.database_url
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=os.getenv("SQL_ECHO") == "1",
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for workers and scripts."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency.

    Commit is explicit inside handlers so a route can compose several domain
    operations into one transaction.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def rows_affected(session: Session, statement: Executable) -> int:
    """Runs a conditional UPDATE and reports how many rows it matched.

    Every state transition in the domain is expressed as an UPDATE guarded by a
    WHERE clause, so the row count *is* the answer to "was this transition
    legal". `Session.execute` is typed as returning `Result`, which has no
    `rowcount`, hence the cast.
    """
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def reset_engine_cache() -> None:
    """Drops cached engines. Used by tests after switching environment."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()
