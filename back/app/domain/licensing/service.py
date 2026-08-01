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

from app.domain.errors import LicenseNotRemixable, NotFound, WorkPrivate
from app.models import LicenseSnapshot, Profile, User, Work, WorkVersion
from app.models.base import utcnow
from app.models.enums import LicenseType, LifecycleStatus, Visibility

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


def can_remix(work: Work, viewer_user_id: str | None) -> bool:
    """Authors may iterate on their own work regardless of public licence."""
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        return False
    if work.owner_user_id == viewer_user_id:
        return True
    return Visibility(work.visibility).allows_remix


def assert_viewable(work: Work, viewer_user_id: str | None, viewer_is_staff: bool = False) -> None:
    if not can_view(work, viewer_user_id, viewer_is_staff):
        raise WorkPrivate()


def assert_remixable(work: Work, viewer_user_id: str | None) -> None:
    """Guards the remix entry point.

    Public but view-only works must fail here even when the caller hits the API
    directly, which is what stops the UI restriction being bypassed.
    """
    assert_viewable(work, viewer_user_id)
    if not can_remix(work, viewer_user_id):
        raise LicenseNotRemixable()


def resolve_license_type(work: Work) -> str:
    """Maps visibility onto the licence a remixer receives."""
    if Visibility(work.visibility).allows_remix:
        return LicenseType.CC_BY_4_0
    return LicenseType.ALL_RIGHTS_RESERVED


def build_attribution(display_name: str, handle: str, title: str) -> str:
    return f"《{title}》 by {display_name} (@{handle})"


def capture_license_snapshot(
    session: Session,
    *,
    source_version: WorkVersion,
    work: Work,
    captured_at: dt.datetime | None = None,
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
    snapshot = LicenseSnapshot(
        license_type=license_type,
        permissions_json=dict(LICENSE_PERMISSIONS[license_type]),
        attribution_text=build_attribution(display_name, handle, source_version.title),
        source_work_version_id=source_version.id,
        captured_at=captured_at or utcnow(),
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
