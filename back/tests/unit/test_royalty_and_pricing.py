"""Royalty split and quoting."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.credits.pricing import DEFAULT_TIER_PRICING, quote
from app.domain.credits.royalty import RoyaltyRule, plan_royalties
from app.models import User
from app.models.enums import Operation, QualityTier
from tests.conftest import make_user


def test_quote_is_deterministic() -> None:
    first = quote(operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    second = quote(operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)

    assert first == second


def test_higher_tier_never_costs_less() -> None:
    for operation, tiers in DEFAULT_TIER_PRICING.items():
        preview = quote(operation=operation, quality_tier=QualityTier.PREVIEW).credits
        standard = quote(operation=operation, quality_tier=QualityTier.STANDARD).credits
        cinematic = quote(operation=operation, quality_tier=QualityTier.CINEMATIC).credits
        assert preview < standard < cinematic, operation
        assert set(tiers) == {
            QualityTier.PREVIEW,
            QualityTier.STANDARD,
            QualityTier.CINEMATIC,
        }


def test_video_duration_adds_a_surcharge() -> None:
    short = quote(
        operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.STANDARD, duration_seconds=4
    )
    long = quote(
        operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.STANDARD, duration_seconds=10
    )

    assert long.credits > short.credits
    assert long.estimated_seconds > short.estimated_seconds


def test_unpriced_combination_is_rejected() -> None:
    with pytest.raises(ValueError, match="未定价"):
        quote(operation="unknown_op", quality_tier=QualityTier.STANDARD)


def test_royalty_rate_decays_with_distance() -> None:
    plans = plan_royalties(
        base_amount=1000, ancestor_author_ids=["a", "b", "c"], rule=RoyaltyRule()
    )

    assert [p.amount for p in plans] == [100, 50, 25]
    assert [p.level for p in plans] == [1, 2, 3]


def test_royalty_total_respects_the_cap() -> None:
    rule = RoyaltyRule(first_level_rate_bps=1500, decay_bps=10_000, total_cap_bps=2000)

    plans = plan_royalties(base_amount=1000, ancestor_author_ids=["a", "b", "c"], rule=rule)

    assert sum(p.amount for p in plans) <= 200


def test_royalty_stops_below_the_minimum_payout() -> None:
    """Rounding to zero ends the chain rather than emitting empty transfers."""
    plans = plan_royalties(base_amount=100, ancestor_author_ids=["a", "b", "c"], rule=RoyaltyRule())

    # 10 for the parent, 5 for the grandparent, then 2 — all still payable.
    assert [p.amount for p in plans] == [10, 5, 2]

    tiny = plan_royalties(base_amount=5, ancestor_author_ids=["a", "b"], rule=RoyaltyRule())
    assert tiny == []


def test_royalty_respects_max_levels() -> None:
    rule = RoyaltyRule(max_levels=2)

    plans = plan_royalties(base_amount=1000, ancestor_author_ids=["a", "b", "c", "d"], rule=rule)

    assert len(plans) == 2


def test_disabled_rule_pays_nothing() -> None:
    plans = plan_royalties(
        base_amount=1000, ancestor_author_ids=["a"], rule=RoyaltyRule(enabled=False)
    )

    assert plans == []


def test_transfer_moves_credits_between_accounts(db: Session, author: User) -> None:
    payer = make_user(db, email="payer@example.com", handle="payer")
    credits.grant(db, payer.id, 500, idempotency_key="grant-payer")
    credits.get_or_create_account(db, author.id)

    result = credits.royalty_transfer(
        db,
        from_user_id=payer.id,
        to_user_id=author.id,
        amount=50,
        work_version_id="wv_test",
        idempotency_key="publish-1",
    )

    assert result is not None
    assert credits.get_account(db, payer.id).available_balance == 450
    assert credits.get_account(db, author.id).available_balance == 50


def test_transfer_is_skipped_when_the_payer_cannot_afford_it(db: Session, author: User) -> None:
    """Royalties are a bonus; they must never block a publication."""
    payer = make_user(db, email="broke@example.com", handle="broke")
    credits.grant(db, payer.id, 10, idempotency_key="grant-broke")

    result = credits.royalty_transfer(
        db,
        from_user_id=payer.id,
        to_user_id=author.id,
        amount=50,
        work_version_id="wv_test",
        idempotency_key="publish-1",
    )

    assert result is None
    assert credits.get_account(db, payer.id).available_balance == 10


def test_author_never_pays_royalties_to_themselves(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-self")

    result = credits.royalty_transfer(
        db,
        from_user_id=author.id,
        to_user_id=author.id,
        amount=10,
        work_version_id="wv_test",
        idempotency_key="publish-1",
    )

    assert result is None
    assert credits.get_account(db, author.id).available_balance == 100
