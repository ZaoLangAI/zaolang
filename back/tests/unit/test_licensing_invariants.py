"""Visibility and remix authorisation."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import LicenseNotRemixable, WorkPrivate
from app.domain.licensing import service as licensing
from app.models import User
from app.models.enums import LicenseType, LifecycleStatus, Visibility
from tests.factories import make_work


def test_default_visibility_is_public_view_only(db: Session, author: User) -> None:
    """The product rule: sharing must not silently grant remix rights."""
    from app.models import Work

    work = Work(owner_user_id=author.id)
    db.add(work)
    db.flush()

    assert work.visibility == Visibility.PUBLIC_VIEW_ONLY


def test_view_only_work_cannot_be_remixed_by_others(
    db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)

    assert licensing.can_view(work, remixer.id) is True
    with pytest.raises(LicenseNotRemixable):
        licensing.assert_remixable(work, remixer.id)


def test_author_may_always_iterate_on_their_own_work(db: Session, author: User) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)

    licensing.assert_remixable(work, author.id)


def test_private_work_is_invisible_to_others(db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PRIVATE)

    with pytest.raises(WorkPrivate):
        licensing.assert_viewable(work, remixer.id)
    licensing.assert_viewable(work, author.id)


def test_private_work_reports_not_found_rather_than_forbidden(db: Session, author: User) -> None:
    """A 403 would confirm the ID exists; the design requires 404."""
    work, _ = make_work(db, author, visibility=Visibility.PRIVATE)

    with pytest.raises(WorkPrivate) as exc:
        licensing.assert_viewable(work, "usr_someone_else")

    assert exc.value.http_status == 404


def test_tombstoned_work_cannot_be_remixed(db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(
        db,
        author,
        visibility=Visibility.PUBLIC_REMIXABLE,
        lifecycle_status=LifecycleStatus.TOMBSTONE,
    )

    assert licensing.can_remix(work, remixer.id) is False


def test_staff_can_view_anything(db: Session, author: User) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PRIVATE)

    assert licensing.can_view(work, "usr_reviewer", viewer_is_staff=True) is True


def test_snapshot_freezes_terms_at_capture_time(db: Session, author: User) -> None:
    """A later licence downgrade must not retroactively invalidate a remix."""
    work, version = make_work(db, author, visibility=Visibility.PUBLIC_REMIXABLE)

    snapshot = licensing.capture_license_snapshot(db, source_version=version, work=work)

    work.visibility = Visibility.PUBLIC_VIEW_ONLY
    db.flush()
    db.refresh(snapshot)

    assert snapshot.license_type == LicenseType.CC_BY_4_0
    assert snapshot.permissions_json["derivative_works"] is True
    assert snapshot.source_work_version_id == version.id


def test_snapshot_carries_attribution_text(db: Session, author: User) -> None:
    work, version = make_work(db, author, title="深海霓虹")

    snapshot = licensing.capture_license_snapshot(db, source_version=version, work=work)

    assert "深海霓虹" in snapshot.attribution_text
    assert "@author" in snapshot.attribution_text


def test_view_only_source_yields_all_rights_reserved(db: Session, author: User) -> None:
    work, version = make_work(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)

    snapshot = licensing.capture_license_snapshot(db, source_version=version, work=work)

    assert snapshot.license_type == LicenseType.ALL_RIGHTS_RESERVED
    assert snapshot.permissions_json["derivative_works"] is False
