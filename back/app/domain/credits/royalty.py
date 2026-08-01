"""Royalty distribution to ancestor authors.

When a remix is published, a share of the generation cost flows back up the
creative chain. Rates decay by depth so a long chain cannot cost more than the
configured cap, and the payer is never pushed into a negative balance.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.lineage import service as lineage_service


@dataclass(frozen=True, slots=True)
class RoyaltyRule:
    enabled: bool = True
    # Share of the job's settled cost paid to the immediate parent author.
    first_level_rate_bps: int = 1000  # 10%
    # Each further level up receives this fraction of the level below it.
    decay_bps: int = 5000  # 50%
    max_levels: int = 3
    min_payout: int = 1
    # Hard ceiling as a share of the settled cost, across all levels.
    total_cap_bps: int = 2000  # 20%


@dataclass(frozen=True, slots=True)
class RoyaltyPlan:
    beneficiary_user_id: str
    amount: int
    level: int


def plan_royalties(
    *, base_amount: int, ancestor_author_ids: list[str], rule: RoyaltyRule
) -> list[RoyaltyPlan]:
    """Computes what each ancestor should receive.

    Pure function so the split can be unit-tested and previewed in the ops
    console without touching any account.
    """
    if not rule.enabled or base_amount <= 0 or not ancestor_author_ids:
        return []

    cap = base_amount * rule.total_cap_bps // 10_000
    plans: list[RoyaltyPlan] = []
    spent = 0
    rate_bps = rule.first_level_rate_bps

    for level, author_id in enumerate(ancestor_author_ids[: rule.max_levels], start=1):
        amount = base_amount * rate_bps // 10_000
        if amount < rule.min_payout:
            break
        if spent + amount > cap:
            amount = cap - spent
        if amount < rule.min_payout:
            break
        plans.append(RoyaltyPlan(beneficiary_user_id=author_id, amount=amount, level=level))
        spent += amount
        rate_bps = rate_bps * rule.decay_bps // 10_000

    return plans


def distribute(
    session: Session,
    *,
    payer_user_id: str,
    child_work_version_id: str,
    base_amount: int,
    rule: RoyaltyRule,
    idempotency_key: str,
) -> list[RoyaltyPlan]:
    """Executes the plan. Skips any leg the payer cannot afford."""
    if not rule.enabled:
        return []

    author_ids = lineage_service.ancestor_author_ids(
        session, child_work_version_id, rule.max_levels
    )
    author_ids = [uid for uid in author_ids if uid != payer_user_id]
    plans = plan_royalties(base_amount=base_amount, ancestor_author_ids=author_ids, rule=rule)

    executed: list[RoyaltyPlan] = []
    for plan in plans:
        result = credits_service.royalty_transfer(
            session,
            from_user_id=payer_user_id,
            to_user_id=plan.beneficiary_user_id,
            amount=plan.amount,
            work_version_id=child_work_version_id,
            idempotency_key=idempotency_key,
        )
        if result is not None:
            executed.append(plan)
    return executed
