"""Paid unlock of remixable works and published skills.

A grant is a one-time receipt. Free subjects and the owner's own work/skill
never write a grant or a ledger row. Paid unlocks transfer credits in the
same transaction as the grant insert so a failed payment cannot leave a
dangling receipt.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.errors import (
    AccessRequired,
    Conflict,
    LicenseNotRemixable,
    NotFound,
    ValidationFailed,
    WorkPrivate,
)
from app.domain.notifications import push as notifications
from app.models import AccessGrant, CreationSkill, Work
from app.models.enums import (
    AccessSubjectType,
    CreationSkillStatus,
    LifecycleStatus,
    NotificationType,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import MarketplaceConfig


@dataclass(frozen=True, slots=True)
class UnlockQuote:
    price: int
    platform_fee: int
    seller_net: int


def has_grant(
    session: Session,
    *,
    buyer_user_id: str,
    subject_type: AccessSubjectType | str,
    subject_id: str,
) -> bool:
    return (
        get_grant(
            session,
            buyer_user_id=buyer_user_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        is not None
    )


def get_grant(
    session: Session,
    *,
    buyer_user_id: str,
    subject_type: AccessSubjectType | str,
    subject_id: str,
) -> AccessGrant | None:
    return session.scalar(
        select(AccessGrant).where(
            AccessGrant.buyer_user_id == buyer_user_id,
            AccessGrant.subject_type == str(subject_type),
            AccessGrant.subject_id == subject_id,
        )
    )


def viewer_unlocked_work(session: Session, work: Work, viewer_id: str | None) -> bool:
    if viewer_id is not None and work.owner_user_id == viewer_id:
        return True
    if (work.access_credits or 0) <= 0:
        return True
    if viewer_id is None:
        return False
    return has_grant(
        session,
        buyer_user_id=viewer_id,
        subject_type=AccessSubjectType.WORK,
        subject_id=work.id,
    )


def viewer_unlocked_skill(session: Session, skill: CreationSkill, viewer_id: str | None) -> bool:
    if viewer_id is not None and skill.owner_user_id == viewer_id:
        return True
    if (skill.access_credits or 0) <= 0:
        return True
    if viewer_id is None:
        return False
    return has_grant(
        session,
        buyer_user_id=viewer_id,
        subject_type=AccessSubjectType.SKILL,
        subject_id=skill.id,
    )


def assert_work_unlocked(session: Session, work: Work, viewer_id: str | None) -> None:
    if viewer_unlocked_work(session, work, viewer_id):
        return
    raise AccessRequired(
        subject_type=AccessSubjectType.WORK.value,
        subject_id=work.id,
        access_credits=work.access_credits,
    )


def assert_skill_unlocked(session: Session, skill: CreationSkill, viewer_id: str | None) -> None:
    if viewer_unlocked_skill(session, skill, viewer_id):
        return
    raise AccessRequired(
        subject_type=AccessSubjectType.SKILL.value,
        subject_id=skill.id,
        access_credits=skill.access_credits,
    )


def normalize_access_credits(
    session: Session,
    value: int,
    *,
    actor_user_id: str | None,
) -> int:
    if value < 0:
        raise ValidationFailed("解锁价格不能为负数。", fields={"access_credits": "必须为非负整数"})
    if value == 0:
        return 0
    if not config_service.is_enabled(session, "marketplace_enabled", user_id=actor_user_id):
        raise ValidationFailed(
            "市场已关闭，不能设置付费标价。",
            fields={"access_credits": "市场已关闭"},
        )
    cfg = config_service.get_typed(session, "marketplace", MarketplaceConfig)
    if value > cfg.max_access_credits:
        raise ValidationFailed(
            f"解锁价格不能超过 {cfg.max_access_credits}。",
            fields={"access_credits": f"上限 {cfg.max_access_credits}"},
        )
    return value


def quote_unlock(session: Session, price: int) -> UnlockQuote:
    cfg = config_service.get_typed(session, "marketplace", MarketplaceConfig)
    fee = price * cfg.platform_fee_bps // 10_000
    return UnlockQuote(price=price, platform_fee=fee, seller_net=price - fee)


def unlock_work(session: Session, *, buyer_user_id: str, work_id: str) -> AccessGrant | None:
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != buyer_user_id and (
        work.visibility == Visibility.PRIVATE or work.lifecycle_status != LifecycleStatus.ACTIVE
    ):
        raise WorkPrivate()
    if (
        work.lifecycle_status != LifecycleStatus.ACTIVE
        or not Visibility(work.visibility).allows_remix
    ):
        raise LicenseNotRemixable()
    if work.owner_user_id == buyer_user_id or (work.access_credits or 0) <= 0:
        return get_grant(
            session,
            buyer_user_id=buyer_user_id,
            subject_type=AccessSubjectType.WORK,
            subject_id=work.id,
        )
    return _unlock(
        session,
        buyer_user_id=buyer_user_id,
        seller_user_id=work.owner_user_id,
        subject_type=AccessSubjectType.WORK,
        subject_id=work.id,
        price=work.access_credits,
        title=None,
    )


def unlock_skill(session: Session, *, buyer_user_id: str, skill_id: str) -> AccessGrant | None:
    skill = session.get(CreationSkill, skill_id)
    if skill is None or skill.status != CreationSkillStatus.PUBLISHED:
        raise NotFound("技能不存在。")
    if skill.owner_user_id == buyer_user_id or (skill.access_credits or 0) <= 0:
        return get_grant(
            session,
            buyer_user_id=buyer_user_id,
            subject_type=AccessSubjectType.SKILL,
            subject_id=skill.id,
        )
    return _unlock(
        session,
        buyer_user_id=buyer_user_id,
        seller_user_id=skill.owner_user_id,
        subject_type=AccessSubjectType.SKILL,
        subject_id=skill.id,
        price=skill.access_credits,
        title=skill.title,
    )


def _unlock(
    session: Session,
    *,
    buyer_user_id: str,
    seller_user_id: str,
    subject_type: AccessSubjectType,
    subject_id: str,
    price: int,
    title: str | None,
) -> AccessGrant:
    existing = get_grant(
        session,
        buyer_user_id=buyer_user_id,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    if existing is not None:
        return existing

    if not config_service.is_enabled(session, "marketplace_enabled", user_id=buyer_user_id):
        raise ValidationFailed("市场已关闭，暂时无法解锁。")
    if price <= 0:
        raise Conflict("该内容无需解锁。")

    quote = quote_unlock(session, price)
    idempotency_key = f"access:{buyer_user_id}:{subject_type.value}:{subject_id}"
    metadata = {
        "subject_type": subject_type.value,
        "subject_id": subject_id,
        "price_credits": quote.price,
        "platform_fee_credits": quote.platform_fee,
        "seller_net_credits": quote.seller_net,
    }

    try:
        credits_service.access_transfer(
            session,
            from_user_id=buyer_user_id,
            to_user_id=seller_user_id,
            price=quote.price,
            platform_fee=quote.platform_fee,
            seller_net=quote.seller_net,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        grant = AccessGrant(
            buyer_user_id=buyer_user_id,
            seller_user_id=seller_user_id,
            subject_type=subject_type.value,
            subject_id=subject_id,
            price_credits=quote.price,
            platform_fee_credits=quote.platform_fee,
            seller_net_credits=quote.seller_net,
        )
        session.add(grant)
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        replay = get_grant(
            session,
            buyer_user_id=buyer_user_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        if replay is not None:
            return replay
        raise Conflict("解锁已被并发处理，请重试。") from exc
    except Conflict as exc:
        replay = get_grant(
            session,
            buyer_user_id=buyer_user_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        if replay is not None:
            return replay
        raise exc

    notifications.notify(
        session,
        user_id=seller_user_id,
        type=NotificationType.ACCESS_SOLD,
        title_key="notification.access_sold",
        payload={
            "amount": quote.seller_net,
            "subject_type": subject_type.value,
            "subject_id": subject_id,
            "title": title or "",
        },
        target_type=subject_type.value,
        target_id=subject_id,
    )
    return grant
