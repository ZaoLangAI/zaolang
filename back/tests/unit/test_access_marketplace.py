"""Paid unlock grants, forced transfers, and remix/skill access gates."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.access import service as access_service
from app.domain.credits import service as credits
from app.domain.errors import AccessRequired, InsufficientCredits, LicenseNotRemixable
from app.domain.licensing import service as licensing
from app.domain.publishing import service as publishing
from app.domain.skill_library import service as skill_library
from app.models import AccessGrant, CreditLedgerEntry, User
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    LedgerEntryType,
    LicenseType,
    Visibility,
)
from tests.factories import make_work


def _fund(db: Session, user: User, amount: int = 100) -> None:
    credits.grant(db, user.id, amount, idempotency_key=f"seed:{user.id}:{amount}")


def test_free_remixable_work_stays_unlocked(db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author)

    licensing.assert_remixable(work, remixer.id, db)
    assert licensing.can_remix(work, remixer.id, db) is True
    assert licensing.remix_block_reason(work, remixer.id, db) is None


def test_paid_work_requires_a_grant(db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author, access_credits=10)

    with pytest.raises(AccessRequired) as exc:
        licensing.assert_remixable(work, remixer.id, db)

    assert exc.value.code == "ACCESS_REQUIRED"
    assert exc.value.http_status == 402
    assert exc.value.details["access_credits"] == 10
    assert licensing.can_remix(work, remixer.id, db) is False
    assert licensing.remix_block_reason(work, remixer.id, db) == "needs_unlock"


def test_author_may_remix_their_own_paid_work_for_free(db: Session, author: User) -> None:
    work, _ = make_work(db, author, access_credits=10)

    licensing.assert_remixable(work, author.id, db)
    grant = access_service.unlock_work(db, buyer_user_id=author.id, work_id=work.id)
    assert grant is None
    assert _ledger_count(db, author.id) == 0


def test_grant_allows_unlimited_drafts(db: Session, author: User, remixer: User) -> None:
    _fund(db, remixer, 100)
    work, _ = make_work(db, author, access_credits=10)

    access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)
    first = publishing.create_draft(db, user_id=remixer.id, source_work_id=work.id)
    second = publishing.create_draft(db, user_id=remixer.id, source_work_id=work.id)

    assert first.id != second.id
    assert _ledger_count(db, remixer.id, LedgerEntryType.ACCESS_OUT) == 1


def test_view_only_blocks_even_with_a_grant(db: Session, author: User, remixer: User) -> None:
    _fund(db, remixer, 100)
    work, _ = make_work(db, author, access_credits=10)
    access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)

    work.visibility = Visibility.PUBLIC_VIEW_ONLY
    db.flush()

    with pytest.raises(LicenseNotRemixable):
        licensing.assert_remixable(work, remixer.id, db)
    assert licensing.remix_block_reason(work, remixer.id, db) == "view_only"


def test_publish_recheck_ignores_a_later_price_hike(
    db: Session, author: User, remixer: User
) -> None:
    _fund(db, remixer, 100)
    work, _ = make_work(db, author, access_credits=10)
    access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)
    publishing.create_draft(db, user_id=remixer.id, source_work_id=work.id)

    work.access_credits = 50
    db.flush()

    licensing.assert_source_still_remixable(work, remixer.id)
    assert _ledger_count(db, remixer.id, LedgerEntryType.ACCESS_OUT) == 1


def test_paid_snapshot_uses_zaolang_paid_remix(db: Session, author: User, remixer: User) -> None:
    _fund(db, remixer, 100)
    work, version = make_work(db, author, title="付费原作", access_credits=10)
    grant = access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)
    assert grant is not None

    snapshot = licensing.capture_license_snapshot(
        db, source_version=version, work=work, remixer_user_id=remixer.id
    )

    assert snapshot.license_type == LicenseType.ZAOLANG_PAID_REMIX
    assert snapshot.access_credits == 10
    assert snapshot.access_grant_id == grant.id
    assert snapshot.permissions_json["attribution_required"] is True
    assert snapshot.permissions_json["derivative_works"] is True


def test_access_transfer_conserves_and_burns_the_fee(
    db: Session, author: User, remixer: User
) -> None:
    _fund(db, remixer, 100)
    credits.access_transfer(
        db,
        from_user_id=remixer.id,
        to_user_id=author.id,
        price=10,
        platform_fee=1,
        seller_net=9,
        idempotency_key="access:test:work:one",
    )

    buyer = credits.get_account(db, remixer.id)
    seller = credits.get_account(db, author.id)
    assert buyer.available_balance == 90
    assert seller.available_balance == 9


def test_insufficient_credits_leave_no_grant(db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author, access_credits=10)

    with pytest.raises(InsufficientCredits):
        access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)

    assert (
        db.scalar(
            select(func.count())
            .select_from(AccessGrant)
            .where(AccessGrant.buyer_user_id == remixer.id)
        )
        == 0
    )


def test_unlock_is_idempotent(db: Session, author: User, remixer: User) -> None:
    _fund(db, remixer, 100)
    work, _ = make_work(db, author, access_credits=10)

    first = access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)
    second = access_service.unlock_work(db, buyer_user_id=remixer.id, work_id=work.id)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert _ledger_count(db, remixer.id, LedgerEntryType.ACCESS_OUT) == 1
    assert credits.get_account(db, remixer.id).available_balance == 90


def test_paid_skill_is_visible_but_locked_until_unlocked(
    db: Session, author: User, remixer: User
) -> None:
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="黄金时刻",
        description="镜头",
        category=CreationSkillCategory.LENS,
        params_json={"prompt_suffix": "golden hour"},
        cover_asset_id=None,
        access_credits=8,
    )
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()

    visible = skill_library.get_usable(db, skill_id=skill.id, viewer_id=remixer.id)
    assert visible.id == skill.id
    assert skill_library.viewer_has_access(db, skill, remixer.id) is False
    with pytest.raises(AccessRequired):
        skill_library.assert_unlocked_for_use(db, skill, remixer.id)


def _ledger_count(db: Session, user_id: str, entry_type: LedgerEntryType | None = None) -> int:
    from app.models import CreditAccount

    account = db.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    if account is None:
        return 0
    stmt = (
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(CreditLedgerEntry.account_id == account.id)
    )
    if entry_type is not None:
        stmt = stmt.where(CreditLedgerEntry.type == entry_type)
    return int(db.scalar(stmt) or 0)
