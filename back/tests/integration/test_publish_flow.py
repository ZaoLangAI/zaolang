"""The eight-step publish transaction and the remix chain it produces."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.errors import (
    Conflict,
    Forbidden,
    LicenseNotRemixable,
    ModerationRejected,
    ValidationFailed,
)
from app.domain.jobs import service as jobs_service
from app.domain.publishing import service as publishing
from app.models import (
    CreditLedgerEntry,
    Draft,
    LineageEdge,
    Notification,
    User,
    Work,
    WorkTag,
    WorkVersion,
)
from app.models.base import new_id
from app.models.enums import (
    LedgerEntryType,
    LifecycleStatus,
    NotificationType,
    Operation,
    QualityTier,
    Visibility,
)
from app.workers import pipeline


def _fund(db: Session, user: User, amount: int = 5_000) -> None:
    credits_service.grant(db, user.id, amount, idempotency_key=new_id("grant"))
    db.flush()


def _generate_into_draft(db: Session, user: User, draft: Draft) -> None:
    """Runs a real generation so the draft has an output asset to publish."""
    result = jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雾气弥漫的山谷", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        draft_id=draft.id,
    )
    draft.latest_job_id = result.job.id
    db.flush()
    pipeline.run_generation_pipeline(db, result.job.id)
    db.refresh(draft)


def _publish(
    db: Session,
    user: User,
    draft: Draft,
    *,
    title: str = "雾谷",
    visibility: str = Visibility.PUBLIC_REMIXABLE,
    tags: list[str] | None = None,
) -> publishing.PublishOutcome:
    return publishing.publish(
        db,
        user_id=user.id,
        draft_id=draft.id,
        title=title,
        description="山谷里的晨雾。",
        visibility=visibility,
        tags=tags if tags is not None else ["cinematic", "landscape"],
        cover_asset_id=None,
        rights_confirmed=True,
    )


@pytest.fixture
def original(db: Session, author: User) -> publishing.PublishOutcome:
    _fund(db, author)
    draft = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "雾气弥漫的山谷", "aspect_ratio": "16:9"},
    )
    _generate_into_draft(db, author, draft)
    return _publish(db, author, draft)


def test_publishing_creates_a_work_and_an_immutable_first_version(
    db: Session, original: publishing.PublishOutcome
) -> None:
    assert original.version.version_number == 1
    assert original.work.current_version_id == original.version.id
    assert original.work.lifecycle_status == LifecycleStatus.ACTIVE
    assert original.work.published_at is not None


def test_publishing_makes_the_output_media_readable(
    db: Session, original: publishing.PublishOutcome
) -> None:
    from app.models import Asset

    asset = db.get(Asset, original.version.primary_output_asset_id)
    assert asset is not None
    assert asset.visibility == Visibility.PUBLIC_VIEW_ONLY


def test_publishing_without_confirming_rights_is_refused(db: Session, author: User) -> None:
    _fund(db, author)
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    _generate_into_draft(db, author, draft)

    with pytest.raises(ValidationFailed):
        publishing.publish(
            db,
            user_id=author.id,
            draft_id=draft.id,
            title="未确认",
            description=None,
            visibility=Visibility.PUBLIC_VIEW_ONLY,
            tags=[],
            cover_asset_id=None,
            rights_confirmed=False,
        )


def test_a_draft_without_output_cannot_be_published(db: Session, author: User) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    with pytest.raises(ValidationFailed):
        _publish(db, author, draft)


def test_a_draft_cannot_be_published_twice(
    db: Session, author: User, original: publishing.PublishOutcome
) -> None:
    """A second publish would create a second work claiming the same lineage."""
    draft = db.scalar(select(Draft).where(Draft.published_work_id == original.work.id))
    assert draft is not None
    with pytest.raises(Conflict):
        _publish(db, author, draft)


def test_another_user_cannot_publish_your_draft(db: Session, author: User, remixer: User) -> None:
    _fund(db, author)
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    _generate_into_draft(db, author, draft)

    with pytest.raises(Forbidden):
        _publish(db, remixer, draft)


def test_an_unsafe_title_is_rejected_before_anything_is_written(db: Session, author: User) -> None:
    """The rollback matters: a half-published work would appear in discovery
    without its lineage."""
    _fund(db, author)
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    _generate_into_draft(db, author, draft)
    before = len(list(db.scalars(select(Work))))

    with pytest.raises(ModerationRejected):
        _publish(db, author, draft, title="未成年人的亲密画面")

    db.rollback()
    assert len(list(db.scalars(select(Work)))) == before


def test_a_view_only_work_does_not_ship_its_parameters(db: Session, author: User) -> None:
    """Publishing view-only and still exposing the full prompt would make the
    licence meaningless."""
    _fund(db, author)
    draft = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "秘密配方"}
    )
    _generate_into_draft(db, author, draft)
    outcome = _publish(db, author, draft, visibility=Visibility.PUBLIC_VIEW_ONLY)

    assert outcome.version.reusable_params_json == {}


def test_a_remixable_work_ships_its_parameters(
    db: Session, original: publishing.PublishOutcome
) -> None:
    assert original.version.reusable_params_json != {}


def test_tags_are_attached_and_counted(db: Session, original: publishing.PublishOutcome) -> None:
    links = list(db.scalars(select(WorkTag).where(WorkTag.work_id == original.work.id)))
    assert len(links) == 2


def test_a_remix_of_a_remixable_work_creates_exactly_one_lineage_edge(
    db: Session, original: publishing.PublishOutcome, remixer: User
) -> None:
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    child = _publish(db, remixer, draft, title="雾谷 · 夜")

    assert child.lineage_edge is not None
    edges = list(
        db.scalars(select(LineageEdge).where(LineageEdge.child_work_version_id == child.version.id))
    )
    assert len(edges) == 1
    assert edges[0].parent_work_version_id == original.version.id


def test_a_remix_bumps_the_parents_counter(
    db: Session, original: publishing.PublishOutcome, remixer: User
) -> None:
    before = original.work.remix_count
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    _publish(db, remixer, draft, title="雾谷 · 夜")

    db.refresh(original.work)
    assert original.work.remix_count == before + 1


def test_a_remix_notifies_the_original_author(
    db: Session, author: User, original: publishing.PublishOutcome, remixer: User
) -> None:
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    _publish(db, remixer, draft, title="雾谷 · 夜")

    notes = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == author.id,
                Notification.type == NotificationType.WORK_REMIXED,
            )
        )
    )
    assert len(notes) == 1


def test_remixing_your_own_work_does_not_notify_you(
    db: Session, author: User, original: publishing.PublishOutcome
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=original.work.id)
    _generate_into_draft(db, author, draft)
    _publish(db, author, draft, title="雾谷 · 自续")

    notes = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == author.id,
                Notification.type == NotificationType.WORK_REMIXED,
            )
        )
    )
    assert notes == []


def test_a_remix_pays_the_ancestor_a_royalty(
    db: Session, author: User, original: publishing.PublishOutcome, remixer: User
) -> None:
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    child = _publish(db, remixer, draft, title="雾谷 · 夜")

    assert child.royalties, "二创发布应当向祖先作者回流分成"
    beneficiaries = {r["beneficiary_user_id"] for r in child.royalties}
    assert author.id in beneficiaries

    account = credits_service.get_or_create_account(db, author.id)
    royalty_in = list(
        db.scalars(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.account_id == account.id,
                CreditLedgerEntry.type == LedgerEntryType.ROYALTY_IN,
            )
        )
    )
    assert len(royalty_in) == 1


def test_a_view_only_work_cannot_be_remixed(db: Session, author: User, remixer: User) -> None:
    _fund(db, author)
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    _generate_into_draft(db, author, draft)
    locked = _publish(db, author, draft, visibility=Visibility.PUBLIC_VIEW_ONLY)

    with pytest.raises(LicenseNotRemixable):
        publishing.create_draft(db, user_id=remixer.id, source_work_id=locked.work.id)


def test_revoking_remix_rights_does_not_invalidate_existing_derivatives(
    db: Session, author: User, original: publishing.PublishOutcome, remixer: User
) -> None:
    """The child's licence snapshot was frozen when the draft was created, so a
    later change by the original author cannot retroactively unlicense it."""
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    child = _publish(db, remixer, draft, title="雾谷 · 夜")

    publishing.change_visibility(
        db,
        user_id=author.id,
        work_id=original.work.id,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
    )

    edge = db.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == child.version.id)
    )
    assert edge is not None
    child_work = db.get(Work, child.work.id)
    assert child_work is not None
    assert child_work.lifecycle_status == LifecycleStatus.ACTIVE


def test_a_stranger_cannot_change_visibility(
    db: Session, original: publishing.PublishOutcome, remixer: User
) -> None:
    with pytest.raises(Forbidden):
        publishing.change_visibility(
            db, user_id=remixer.id, work_id=original.work.id, visibility=Visibility.PRIVATE
        )


def test_a_tombstoned_ancestor_keeps_the_chain_resolvable(
    db: Session, author: User, original: publishing.PublishOutcome, remixer: User
) -> None:
    """Descendants must still be able to show where they came from, so the row
    survives as a tombstone rather than being deleted."""
    _fund(db, remixer)
    draft = publishing.create_draft(db, user_id=remixer.id, source_work_id=original.work.id)
    _generate_into_draft(db, remixer, draft)
    child = _publish(db, remixer, draft, title="雾谷 · 夜")

    publishing.tombstone(db, work_id=original.work.id, reason="版权申诉", actor_user_id=author.id)

    db.refresh(original.work)
    assert original.work.lifecycle_status == LifecycleStatus.TOMBSTONE
    assert original.work.visibility == Visibility.PRIVATE

    parent_version = db.get(WorkVersion, original.version.id)
    assert parent_version is not None, "墓碑不能删除版本记录，否则子作品失去溯源"

    edge = db.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == child.version.id)
    )
    assert edge is not None
    assert edge.parent_author_snapshot_json.get("user_id") == author.id
