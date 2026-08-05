"""Promo / invite code redemption.

A code is worth a fixed number of credits to whichever user redeems it,
subject to a use cap and (for invite codes) an expiry. `redeem()` is
idempotent per user: `uq_redemption_records_code_user` makes a second attempt
on the same code by the same user fail closed rather than double-grant.
"""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.models import RedemptionCode, RedemptionRecord
from app.models.base import utcnow
from app.models.enums import RedemptionCodeKind

# Crockford-ish, no 0/O/1/I — read aloud over a support chat without ambiguity.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_code(length: int = 10) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def create_code(
    session: Session,
    *,
    kind: RedemptionCodeKind,
    credits: int,
    max_uses: int = 1,
    expires_at: dt.datetime | None = None,
    note: str | None = None,
    actor_user_id: str,
    code: str | None = None,
) -> RedemptionCode:
    if credits <= 0:
        raise ValidationFailed("赠送积分必须为正数。")
    if max_uses <= 0:
        raise ValidationFailed("可兑换次数必须为正数。")

    entry = RedemptionCode(
        code=(code or generate_code()).strip().upper(),
        kind=kind,
        credits=credits,
        max_uses=max_uses,
        expires_at=expires_at,
        note=note,
        created_by_user_id=actor_user_id,
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("兑换码已存在，请重新生成。") from exc
    return entry


def deactivate_code(session: Session, *, code: RedemptionCode) -> RedemptionCode:
    code.is_active = False
    session.flush()
    return code


def redeem(session: Session, *, code: str, user_id: str) -> RedemptionRecord:
    """The whole exchange: validate the code, book one record, grant credits."""
    entry = session.scalar(
        select(RedemptionCode).where(RedemptionCode.code == code.strip().upper())
    )
    if entry is None:
        raise NotFound("兑换码不存在。")
    if not entry.is_active:
        raise Conflict("兑换码已停用。")
    if entry.expires_at is not None and entry.expires_at < utcnow():
        raise Conflict("兑换码已过期。")
    if entry.used_count >= entry.max_uses:
        raise Conflict("兑换码已达到使用上限。")

    record = RedemptionRecord(
        code_id=entry.id, user_id=user_id, credits=entry.credits, created_at=utcnow()
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("你已经兑换过这个码。") from exc

    entry.used_count += 1
    credits_service.grant(
        session,
        user_id,
        entry.credits,
        idempotency_key=f"redemption:{record.id}",
        metadata={"redemption_code_id": entry.id, "code": entry.code},
    )
    return record


def list_codes(
    session: Session, *, kind: RedemptionCodeKind | None = None, limit: int = 50
) -> list[RedemptionCode]:
    stmt = select(RedemptionCode).order_by(RedemptionCode.created_at.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(RedemptionCode.kind == kind)
    return list(session.scalars(stmt))


def list_records(session: Session, *, code_id: str) -> list[RedemptionRecord]:
    stmt = (
        select(RedemptionRecord)
        .where(RedemptionRecord.code_id == code_id)
        .order_by(RedemptionRecord.created_at.desc())
    )
    return list(session.scalars(stmt))
