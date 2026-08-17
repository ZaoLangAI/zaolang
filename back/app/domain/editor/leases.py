"""Single-writer leases for an EpisodeCut."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.editor.time import LEASE_TTL_SECONDS
from app.domain.errors import LeaseHeld, NotFound
from app.models import EditorLease, EpisodeCut
from app.models.base import utcnow


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _active_lease(session: Session, cut_id: str, *, now: dt.datetime) -> EditorLease | None:
    stmt = select(EditorLease).where(
        EditorLease.cut_id == cut_id,
        EditorLease.revoked_at.is_(None),
        EditorLease.expires_at > now,
    )
    return session.scalar(stmt)


def acquire(
    session: Session,
    *,
    cut: EpisodeCut,
    user_id: str,
    browser_instance_id: str,
    now: dt.datetime | None = None,
) -> tuple[EditorLease, str]:
    moment = now or utcnow()
    existing = _active_lease(session, cut.id, now=moment)
    if existing is not None:
        if existing.user_id != user_id or existing.browser_instance_id != browser_instance_id:
            raise LeaseHeld()
        existing.expires_at = moment + dt.timedelta(seconds=LEASE_TTL_SECONDS)
        session.flush()
        return existing, ""
    # A lease can be expired-but-not-yet-swept by the beat task; the partial
    # unique index only allows one revoked_at IS NULL row per cut, so close
    # it out here instead of waiting up to 60s for expire_editor_leases.
    stale = session.scalar(
        select(EditorLease).where(EditorLease.cut_id == cut.id, EditorLease.revoked_at.is_(None))
    )
    if stale is not None:
        stale.revoked_at = moment
        session.flush()
    token = secrets.token_urlsafe(24)
    lease = EditorLease(
        cut_id=cut.id,
        user_id=user_id,
        browser_instance_id=browser_instance_id,
        token_hash=_hash_token(token),
        base_revision_id=cut.head_revision_id,
        last_sequence=0,
        expires_at=moment + dt.timedelta(seconds=LEASE_TTL_SECONDS),
    )
    session.add(lease)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise LeaseHeld() from error
    return lease, token


def peek_active(
    session: Session, cut_id: str, *, now: dt.datetime | None = None
) -> EditorLease | None:
    return _active_lease(session, cut_id, now=now or utcnow())


def require_write_lease(
    session: Session,
    *,
    cut_id: str,
    user_id: str,
    lease_id: str,
    token: str,
    now: dt.datetime | None = None,
) -> EditorLease:
    moment = now or utcnow()
    lease = session.get(EditorLease, lease_id)
    if lease is None or lease.cut_id != cut_id:
        raise NotFound("编辑租约不存在。")
    if lease.user_id != user_id:
        raise LeaseHeld()
    if lease.revoked_at is not None or lease.expires_at <= moment:
        raise LeaseHeld("编辑租约已过期。")
    if lease.token_hash != _hash_token(token):
        raise LeaseHeld("编辑租约无效。")
    return lease


def heartbeat(
    session: Session,
    *,
    lease: EditorLease,
    now: dt.datetime | None = None,
) -> EditorLease:
    moment = now or utcnow()
    if lease.revoked_at is not None or lease.expires_at <= moment:
        raise LeaseHeld("编辑租约已过期。")
    lease.expires_at = moment + dt.timedelta(seconds=LEASE_TTL_SECONDS)
    session.flush()
    return lease


def release(session: Session, *, lease: EditorLease, now: dt.datetime | None = None) -> None:
    lease.revoked_at = now or utcnow()
    session.flush()
