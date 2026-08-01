"""Shared test fixtures.

Tests run against a real PostgreSQL database (the schema relies on pgvector,
partial indexes and conditional UPDATEs that SQLite cannot reproduce), inside a
transaction that is rolled back after each test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

# Set before any app import so cached settings pick the test database and the
# deterministic LLM stub.
os.environ.setdefault("APP_ENV", "test")
os.environ["LLM_MODE"] = "stub"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_engine
from app.models import Base, Profile, User
from app.models.enums import UserRole
from app.security.passwords import hash_password
from app.security.tokens import issue_admin_token, issue_consumer_tokens


@pytest.fixture(scope="session")
def engine() -> Engine:
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Session bound to a transaction that is always rolled back.

    Nested SAVEPOINTs keep `session.rollback()` inside domain code from
    destroying the outer test transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def truncate_all(engine: Engine) -> None:
    """Empties every table. For tests that commit for real."""
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {names} CASCADE"))


@pytest.fixture
def committed_db(engine: Engine) -> Iterator[Session]:
    """Session whose commits actually land, cleaned up by truncation.

    The rolled-back `db` fixture cannot be used where the code under test calls
    `session.rollback()` — the domain services do that when a unique constraint
    fires, which would discard the fixture's own rows along with the failed
    write. Property and concurrency tests need a baseline that survives a
    rollback, so they commit and pay for a truncation afterwards.
    """
    session = Session(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        truncate_all(engine)


@pytest.fixture(autouse=True)
def _clear_redis_state() -> Iterator[None]:
    """Drops cached config and rate-limit counters between tests.

    Both live in Redis rather than Postgres, so rolling back the transaction
    does not undo them. Without this, a test that disables a provider leaks
    that setting into the next one, and a run of login tests exhausts the
    shared `auth_attempt` budget partway through the file.
    """
    from app.api.rate_limit import RULES, get_redis
    from app.platform_config import service as config_service

    def flush() -> None:
        for key in config_service.all_keys():
            config_service.invalidate(key)
        client = get_redis()
        for bucket in RULES:
            for key in client.scan_iter(match=f"rl:{bucket}:*", count=500):
                client.delete(key)

    flush()
    yield
    flush()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """HTTP client bound to the same rolled-back transaction as `db`.

    Handlers call `session.commit()`, which the savepoint turns into a release
    rather than a real commit, so assertions can read what a handler wrote
    without anything escaping the test.
    """
    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_header(user: User) -> dict[str, str]:
    token, _, _ = issue_consumer_tokens(user.id, list(user.roles))
    return {"Authorization": f"Bearer {token}"}


def admin_header(user: User) -> dict[str, str]:
    token, _ = issue_admin_token(user.id, list(user.roles))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def reviewer(db: Session) -> User:
    return make_user(
        db,
        email="reviewer@example.com",
        handle="reviewer",
        display_name="审核",
        roles=[UserRole.USER.value, UserRole.REVIEWER.value],
    )


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(
        db,
        email="admin@example.com",
        handle="administrator",
        display_name="管理员",
        roles=[UserRole.USER.value, UserRole.ADMIN.value],
    )


def make_user(
    session: Session,
    *,
    email: str,
    handle: str | None = None,
    display_name: str | None = None,
    roles: list[str] | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("Password123!"),
        roles=roles or [UserRole.USER.value],
    )
    session.add(user)
    session.flush()
    profile = Profile(
        user_id=user.id,
        display_name=display_name or email.split("@")[0],
        handle=handle or email.split("@")[0],
    )
    session.add(profile)
    session.flush()
    return user


@pytest.fixture
def author(db: Session) -> User:
    return make_user(db, email="author@example.com", handle="author", display_name="原作者")


@pytest.fixture
def remixer(db: Session) -> User:
    return make_user(db, email="remixer@example.com", handle="remixer", display_name="二创者")


@pytest.fixture
def operator(db: Session) -> User:
    return make_user(
        db,
        email="operator@example.com",
        handle="operator",
        display_name="运营",
        roles=[UserRole.USER.value, UserRole.OPERATOR.value],
    )
