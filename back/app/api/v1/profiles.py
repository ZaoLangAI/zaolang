"""Public profile pages."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.api.schemas.auth import PublicProfileResponse
from app.api.schemas.common import Page
from app.api.schemas.works import WorkSummary
from app.api.v1.works import _summary
from app.domain.errors import NotFound
from app.models import Bookmark, Follow, Profile, Work, WorkVersion
from app.models.enums import LifecycleStatus, Visibility
from app.presenters import media_urls

router = APIRouter(tags=["profiles"])


@router.get("/profiles/{handle}", response_model=PublicProfileResponse)
def get_profile(handle: str, session: DbSession, viewer: OptionalUser) -> PublicProfileResponse:
    profile = session.scalar(select(Profile).where(Profile.handle == handle))
    if profile is None:
        raise NotFound("用户不存在。")

    is_self = viewer is not None and viewer.id == profile.user_id
    if not profile.public_profile and not is_self:
        raise NotFound("用户不存在。")

    return PublicProfileResponse(
        user_id=profile.user_id,
        handle=profile.handle,
        display_name=profile.display_name,
        bio=profile.bio,
        location=profile.location,
        avatar_url=media_urls.asset_url(session, profile.avatar_asset_id),
        cover_url=media_urls.asset_url(session, profile.cover_asset_id),
        work_count=_count(session, Work, Work.owner_user_id == profile.user_id),
        follower_count=_count(session, Follow, Follow.followed_user_id == profile.user_id),
        following_count=_count(session, Follow, Follow.follower_user_id == profile.user_id),
        viewer_following=_viewer_follows(session, viewer, profile.user_id),
        is_self=is_self,
    )


@router.get("/profiles/{handle}/works", response_model=Page[WorkSummary])
def profile_works(
    handle: str,
    session: DbSession,
    viewer: OptionalUser,
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[WorkSummary]:
    profile = session.scalar(select(Profile).where(Profile.handle == handle))
    if profile is None:
        raise NotFound("用户不存在。")

    is_self = viewer is not None and viewer.id == profile.user_id
    stmt = (
        select(Work, WorkVersion)
        .join(WorkVersion, WorkVersion.id == Work.current_version_id)
        .where(Work.owner_user_id == profile.user_id)
        .order_by(Work.published_at.desc().nullslast(), Work.id.desc())
        .limit(limit)
    )
    if not is_self:
        # Visitors see only what is listed publicly and still alive.
        stmt = stmt.where(
            Work.lifecycle_status == LifecycleStatus.ACTIVE,
            Work.visibility.in_(
                [Visibility.PUBLIC_REMIXABLE.value, Visibility.PUBLIC_VIEW_ONLY.value]
            ),
        )

    rows = session.execute(stmt).all()
    return Page(items=[_summary(session, work, version, viewer) for work, version in rows])


@router.get("/me/bookmarks", response_model=Page[WorkSummary])
def my_bookmarks(
    session: DbSession, viewer: CurrentUser, limit: int = Query(default=24, ge=1, le=60)
) -> Page[WorkSummary]:
    rows = session.execute(
        select(Work, WorkVersion)
        .join(Bookmark, Bookmark.work_id == Work.id)
        .join(WorkVersion, WorkVersion.id == Work.current_version_id)
        .where(Bookmark.user_id == viewer.id)
        .order_by(Bookmark.created_at.desc())
        .limit(limit)
    ).all()
    return Page(items=[_summary(session, work, version, viewer) for work, version in rows])


def _count(session, model, condition) -> int:  # type: ignore[no-untyped-def]
    return int(session.scalar(select(func.count()).select_from(model).where(condition)) or 0)


def _viewer_follows(session, viewer, user_id: str) -> bool:  # type: ignore[no-untyped-def]
    if viewer is None:
        return False
    return (
        session.scalar(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_user_id == viewer.id, Follow.followed_user_id == user_id)
        )
        or 0
    ) > 0
