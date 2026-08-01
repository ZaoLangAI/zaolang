"""Ledger reconciliation.

Recomputes every account from its ledger and compares against the stored
balance. Any divergence is a bug in a credit path, and a dangling reservation
is a job whose worker never settled — both are exactly the failures the
invariants are meant to prevent, so they are surfaced rather than repaired
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CreditAccount, CreditLedgerEntry, GenerationJob, ReconciliationReport
from app.models.base import utcnow
from app.models.enums import JobStatus, LedgerEntryType

# Types that move credits into or out of the system as a whole.
EXTERNAL_TYPES = (
    LedgerEntryType.GRANT,
    LedgerEntryType.PURCHASE,
    LedgerEntryType.ADJUSTMENT,
    LedgerEntryType.ROYALTY_IN,
    LedgerEntryType.ROYALTY_OUT,
    LedgerEntryType.REFUND,
)


@dataclass(slots=True)
class AccountMismatch:
    account_id: str
    user_id: str
    stored_available: int
    stored_reserved: int
    derived_total: int


def derive_totals(session: Session, account_id: str) -> int:
    """Credits the account should hold: everything in, minus everything spent."""
    inflow = session.scalar(
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
            CreditLedgerEntry.account_id == account_id,
            CreditLedgerEntry.type.in_([t.value for t in EXTERNAL_TYPES]),
        )
    )
    captured = session.scalar(
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
            CreditLedgerEntry.account_id == account_id,
            CreditLedgerEntry.type == LedgerEntryType.CAPTURE,
        )
    )
    return int(inflow or 0) + int(captured or 0)


def find_mismatches(session: Session) -> list[AccountMismatch]:
    mismatches: list[AccountMismatch] = []
    for account in session.scalars(select(CreditAccount)):
        derived = derive_totals(session, account.id)
        held = account.available_balance + account.reserved_balance
        if derived != held:
            mismatches.append(
                AccountMismatch(
                    account_id=account.id,
                    user_id=account.user_id,
                    stored_available=account.available_balance,
                    stored_reserved=account.reserved_balance,
                    derived_total=derived,
                )
            )
    return mismatches


def find_dangling_reservations(session: Session) -> list[str]:
    """Jobs whose reserve never became a capture or a release.

    A terminal job in this list means a settlement path was missed, which is
    the one thing the ledger design forbids.
    """
    reserved_jobs = set(
        session.scalars(
            select(CreditLedgerEntry.job_id).where(
                CreditLedgerEntry.type == LedgerEntryType.RESERVE,
                CreditLedgerEntry.job_id.is_not(None),
            )
        )
    )
    settled_jobs = set(
        session.scalars(
            select(CreditLedgerEntry.job_id).where(
                CreditLedgerEntry.type.in_(
                    [LedgerEntryType.CAPTURE.value, LedgerEntryType.RELEASE.value]
                ),
                CreditLedgerEntry.job_id.is_not(None),
            )
        )
    )
    unsettled = reserved_jobs - settled_jobs
    if not unsettled:
        return []

    # An in-flight job is expected to be unsettled; only terminal ones are bugs.
    terminal = session.scalars(
        select(GenerationJob.id).where(
            GenerationJob.id.in_(unsettled),
            GenerationJob.status.in_(
                [
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                    JobStatus.EXPIRED.value,
                ]
            ),
        )
    )
    return sorted(str(job_id) for job_id in terminal)


def build_report(session: Session) -> ReconciliationReport:
    mismatches = find_mismatches(session)
    dangling = find_dangling_reservations(session)
    account_count = session.scalar(select(func.count()).select_from(CreditAccount)) or 0

    report = ReconciliationReport(
        generated_at=utcnow(),
        account_count=int(account_count),
        mismatched_account_count=len(mismatches),
        dangling_reserved_count=len(dangling),
        details_json={
            "mismatches": [
                {
                    "account_id": m.account_id,
                    "user_id": m.user_id,
                    "stored_available": m.stored_available,
                    "stored_reserved": m.stored_reserved,
                    "derived_total": m.derived_total,
                }
                for m in mismatches[:50]
            ],
            "dangling_job_ids": dangling[:50],
        },
    )
    session.add(report)
    session.flush()
    return report
