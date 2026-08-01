"""Idempotency for state-changing endpoints.

The contract the API documents:

* same key + same body  → the first response is replayed, no second side effect
* same key + different body → 409 IDEMPOTENCY_CONFLICT

Both cases are decided against a stored request hash rather than by trusting
the client.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import IdempotencyConflict
from app.models import IdempotencyRecord
from app.models.base import utcnow


def hash_request(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def find_replay(
    session: Session, *, user_id: str, endpoint: str, key: str, request_hash: str
) -> IdempotencyRecord | None:
    """Returns the stored response, or raises when the body has changed."""
    stored = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if stored is None:
        return None
    if stored.request_hash != request_hash:
        raise IdempotencyConflict()
    return stored


def remember(
    session: Session,
    *,
    user_id: str,
    endpoint: str,
    key: str,
    request_hash: str,
    status_code: int,
    response: dict[str, Any],
) -> IdempotencyRecord:
    """Stores the outcome so a retry replays it.

    A unique-violation here means another request with the same key won the
    race; that is treated as a conflict rather than overwriting the winner.
    """
    record = IdempotencyRecord(
        user_id=user_id,
        endpoint=endpoint,
        idempotency_key=key,
        request_hash=request_hash,
        response_status=status_code,
        response_snapshot=response,
        created_at=utcnow(),
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise IdempotencyConflict("相同幂等键的请求正在处理中。") from exc
    return record
