"""Puts a subject in front of a human reviewer.

Every caller that produces a `needs_review` verdict — pre-generation safety
checks, publish, skill submission — funnels through here so there is exactly
one place that decides what a queue row looks like and how urgent it is.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ModerationQueueItem, ReportCase
from app.models.enums import ModerationStage, ModerationStatus, ReportStatus

# A subject already live and visible to other users (pre_publish, post_generation,
# skill_review) is worth more of a reviewer's attention than one still gated
# behind generation, which nobody but its owner can see yet.
_STAGE_BASE_PRIORITY: dict[ModerationStage, int] = {
    ModerationStage.PRE_GENERATION: 20,
    ModerationStage.POST_GENERATION: 50,
    ModerationStage.PRE_PUBLISH: 50,
    ModerationStage.SKILL_REVIEW: 40,
}


def enqueue_for_review(
    session: Session,
    *,
    subject_type: str,
    subject_id: str,
    stage: ModerationStage,
    reason_code: str | None,
    categories: Sequence[str] | None = None,
) -> ModerationQueueItem:
    """Opens (or reopens) the one queue row for `(subject_type, subject_id, stage)`.

    `uq_moderation_queue_subject` allows at most one row per key, so a second
    flag on the same subject updates that row rather than piling up
    duplicates — a subject's review history lives in `ModerationResult`, not
    in repeated queue rows.

    If the row is already open (`NEEDS_REVIEW`), only the signal fields are
    refreshed: a reviewer who has claimed it must not have that claim
    silently cleared just because the same subject tripped another check —
    some callers (compliance previews) can run repeatedly on unchanged input.
    A previously *resolved* row is genuinely reopened, which does drop the
    stale claim and resolution.
    """
    item = session.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == subject_type,
            ModerationQueueItem.subject_id == subject_id,
            ModerationQueueItem.stage == stage,
        )
    )
    priority = _priority_for(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        stage=stage,
        categories=categories,
    )

    if item is None:
        item = ModerationQueueItem(
            subject_type=subject_type,
            subject_id=subject_id,
            stage=stage,
            status=ModerationStatus.NEEDS_REVIEW,
            reason_code=reason_code,
            priority=priority,
        )
        session.add(item)
    elif item.status == ModerationStatus.NEEDS_REVIEW:
        item.reason_code = reason_code
        item.priority = priority
    else:
        item.status = ModerationStatus.NEEDS_REVIEW
        item.claimed_by_user_id = None
        item.reason_code = reason_code
        item.resolved_at = None
        item.priority = priority

    session.flush()
    return item


def ensure_work_queue_item(
    session: Session,
    *,
    work_id: str,
    status: ModerationStatus | None = None,
    reason_code: str | None = None,
) -> ModerationQueueItem:
    """Finds or creates the `pre_publish` row for a published work.

    Used when a reviewer acts on a work that Safety auto-approved and never
    enqueued. Does not reopen or rewrite an existing row's status — the
    caller applies the new verdict afterwards.
    """
    item = session.scalar(
        select(ModerationQueueItem)
        .where(
            ModerationQueueItem.subject_type == "work",
            ModerationQueueItem.subject_id == work_id,
            ModerationQueueItem.stage == ModerationStage.PRE_PUBLISH,
        )
        .limit(1)
    )
    if item is not None:
        return item
    item = ModerationQueueItem(
        subject_type="work",
        subject_id=work_id,
        stage=ModerationStage.PRE_PUBLISH,
        status=status or ModerationStatus.APPROVED,
        reason_code=reason_code,
        priority=_STAGE_BASE_PRIORITY[ModerationStage.PRE_PUBLISH],
    )
    session.add(item)
    session.flush()
    return item


def latest_work_queue_item(session: Session, work_id: str) -> ModerationQueueItem | None:
    return session.scalar(
        select(ModerationQueueItem)
        .where(
            ModerationQueueItem.subject_type == "work",
            ModerationQueueItem.subject_id == work_id,
        )
        .order_by(ModerationQueueItem.created_at.desc(), ModerationQueueItem.id.desc())
        .limit(1)
    )


def open_report_count(session: Session, *, subject_type: str, subject_id: str) -> int:
    """How many still-open user reports name this same subject.

    Reports and the moderation queue are independent backlogs with no shared
    row, so this is the cheapest honest link between them: enough for a
    reviewer to know a subject has also been reported, without merging the
    two systems.
    """
    return (
        session.scalar(
            select(func.count())
            .select_from(ReportCase)
            .where(
                ReportCase.subject_type == subject_type,
                ReportCase.subject_id == subject_id,
                ReportCase.status == ReportStatus.OPEN,
            )
        )
        or 0
    )


def _priority_for(
    session: Session,
    *,
    subject_type: str,
    subject_id: str,
    stage: ModerationStage,
    categories: Sequence[str] | None,
) -> int:
    base = _STAGE_BASE_PRIORITY.get(stage, 30)
    category_score = 10 * len(categories or ())
    report_score = 15 * open_report_count(session, subject_type=subject_type, subject_id=subject_id)
    return base + category_score + report_score
