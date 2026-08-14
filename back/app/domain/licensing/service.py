"""Visibility, remix authorisation and licence snapshots.

The rule this module exists to guarantee: a remix draft can only be created
from a version whose work is currently `public_remixable`, and the terms in
force at that moment are frozen into a `LicenseSnapshot` that later licence
changes cannot rewrite.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.access import service as access_service
from app.domain.errors import AccessRequired, LicenseNotRemixable, NotFound, WorkPrivate
from app.models import LicenseSnapshot, Profile, User, Work, WorkVersion
from app.models.base import utcnow
from app.models.enums import AccessSubjectType, LicenseType, LifecycleStatus, Visibility

# What each licence lets a downstream creator do. Frozen into the snapshot so a
# remix is always judged against the terms the remixer actually accepted.
LICENSE_PERMISSIONS: dict[str, dict[str, bool]] = {
    LicenseType.CC_BY_4_0: {
        "commercial_use": True,
        "derivative_works": True,
        "share_alike": False,
        "attribution_required": True,
    },
    LicenseType.CC_BY_SA_4_0: {
        "commercial_use": True,
        "derivative_works": True,
        "share_alike": True,
        "attribution_required": True,
    },
    LicenseType.CC_BY_NC_4_0: {
        "commercial_use": False,
        "derivative_works": True,
        "share_alike": False,
        "attribution_required": True,
    },
    LicenseType.ALL_RIGHTS_RESERVED: {
        "commercial_use": False,
        "derivative_works": False,
        "share_alike": False,
        "attribution_required": True,
    },
    LicenseType.ZAOLANG_PAID_REMIX: {
        "commercial_use": False,
        "derivative_works": True,
        "share_alike": False,
        "attribution_required": True,
    },
}


def can_view(work: Work, viewer_user_id: str | None, viewer_is_staff: bool = False) -> bool:
    if viewer_is_staff:
        return True
    if work.owner_user_id == viewer_user_id:
        return True
    if work.visibility == Visibility.PRIVATE:
        return False
    # Hidden and tombstoned works stay reachable through lineage, but they are
    # not directly viewable.
    return work.lifecycle_status == LifecycleStatus.ACTIVE


def visibility_allows_remix(work: Work) -> bool:
    """Whether the work is offered for remix, ignoring price and grants."""
    return (
        work.lifecycle_status == LifecycleStatus.ACTIVE
        and Visibility(work.visibility).allows_remix
    )


def can_remix(work: Work, viewer_user_id: str | None, session: Session | None = None) -> bool:
    """Authors may iterate on their own work regardless of public licence.

    For everyone else the work must be publicly remixable *and* unlocked
    (price 0 counts as unlocked). `session` is required to see grants; without
    it a paid work is treated as locked.
    """
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        return False
    if work.owner_user_id == viewer_user_id:
        return True
    if not Visibility(work.visibility).allows_remix:
        return False
    if session is None:
        return (work.access_credits or 0) <= 0
    return access_service.viewer_unlocked_work(session, work, viewer_user_id)


def remix_block_reason(
    work: Work, viewer_user_id: str | None, session: Session | None = None
) -> str | None:
    if can_remix(work, viewer_user_id, session):
        return None
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        return "inactive"
    if not Visibility(work.visibility).allows_remix:
        return "view_only"
    return "needs_unlock"


def assert_viewable(work: Work, viewer_user_id: str | None, viewer_is_staff: bool = False) -> None:
    if not can_view(work, viewer_user_id, viewer_is_staff):
        raise WorkPrivate()


def assert_source_still_remixable(work: Work, viewer_user_id: str | None) -> None:
    """Publish re-check: visibility only. An in-flight draft is not re-billed."""
    assert_viewable(work, viewer_user_id)
    if work.owner_user_id == viewer_user_id:
        return
    if not visibility_allows_remix(work):
        raise LicenseNotRemixable()


def assert_remixable(
    work: Work, viewer_user_id: str | None, session: Session | None = None
) -> None:
    """Guards the remix entry point for a *new* draft or job.

    Public but view-only works must fail here even when the caller hits the API
    directly. Paid remixable works fail with `AccessRequired` so the client can
    show an unlock CTA instead of "not remixable".
    """
    assert_viewable(work, viewer_user_id)
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        raise LicenseNotRemixable()
    if work.owner_user_id == viewer_user_id:
        return
    if not Visibility(work.visibility).allows_remix:
        raise LicenseNotRemixable()
    if session is None:
        if (work.access_credits or 0) > 0:
            raise AccessRequired(
                subject_type=AccessSubjectType.WORK.value,
                subject_id=work.id,
                access_credits=work.access_credits,
            )
        return
    access_service.assert_work_unlocked(session, work, viewer_user_id)


def resolve_license_type(work: Work) -> str:
    """Maps visibility and price onto the licence a remixer receives."""
    if not Visibility(work.visibility).allows_remix:
        return LicenseType.ALL_RIGHTS_RESERVED
    if (work.access_credits or 0) > 0:
        return LicenseType.ZAOLANG_PAID_REMIX
    return LicenseType.CC_BY_4_0


def build_attribution(display_name: str, handle: str, title: str) -> str:
    return f"《{title}》 by {display_name} (@{handle})"


def capture_license_snapshot(
    session: Session,
    *,
    source_version: WorkVersion,
    work: Work,
    captured_at: dt.datetime | None = None,
    remixer_user_id: str | None = None,
) -> LicenseSnapshot:
    """Freezes the current licence terms for one remix.

    A new snapshot is written per remix rather than shared, so the audit trail
    records exactly what each downstream creator agreed to and when.
    """
    author = session.get(User, work.owner_user_id)
    if author is None:
        raise NotFound("原作者不存在。")
    profile = session.scalar(select(Profile).where(Profile.user_id == author.id))
    display_name = profile.display_name if profile else author.email.split("@")[0]
    handle = profile.handle if profile else author.id

    license_type = resolve_license_type(work)
    grant_id = None
    if remixer_user_id and (work.access_credits or 0) > 0:
        grant = access_service.get_grant(
            session,
            buyer_user_id=remixer_user_id,
            subject_type=AccessSubjectType.WORK,
            subject_id=work.id,
        )
        grant_id = grant.id if grant is not None else None
    snapshot = LicenseSnapshot(
        license_type=license_type,
        permissions_json=dict(LICENSE_PERMISSIONS[license_type]),
        attribution_text=build_attribution(display_name, handle, source_version.title),
        source_work_version_id=source_version.id,
        captured_at=captured_at or utcnow(),
        access_credits=work.access_credits or 0,
        access_grant_id=grant_id,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def author_snapshot(session: Session, work: Work) -> dict[str, str]:
    """Denormalised author identity stored on the lineage edge.

    Kept as a copy so a tombstoned or renamed author still shows correct
    historical attribution on descendant works.
    """
    author = session.get(User, work.owner_user_id)
    if author is None:
        raise NotFound("原作者不存在。")
    profile = session.scalar(select(Profile).where(Profile.user_id == author.id))
    return {
        "user_id": author.id,
        "display_name": profile.display_name if profile else author.email.split("@")[0],
        "handle": profile.handle if profile else author.id,
        "avatar_asset_id": (profile.avatar_asset_id or "") if profile else "",
    }
