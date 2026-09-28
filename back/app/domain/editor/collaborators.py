"""Series co-creation membership (短剧共创).

A `SeriesCollaborator` row grants a second user the same *management-level*
access as the series owner on a `kind=drama` `Series` — series metadata,
episode CRUD, script writing, content links, generation submission tied to
the series. It never reaches the timeline editor (`EpisodeCut`/leases/
revisions/exports/AI planning), the recycle bin (trash/untrash/purge), or
distribution/publishing — those stay strictly `Series.owner_user_id`-gated
(see `zaolang-editor-drama`). Membership starts as a `pending` invite and
only becomes real access once the invitee calls `accept`.

`is_active_member` is the one function the rest of the domain should call to
ask "can this user manage this series" — never query `SeriesCollaborator`
directly elsewhere (mirrors how `app.domain.licensing.service` is the only
place that answers "can this user view/remix this work").
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.notifications.push import notify
from app.models import Profile, Series, SeriesCollaborator, User
from app.models.base import utcnow
from app.models.enums import NotificationType, SeriesCollaboratorStatus, SeriesKind

# Hardcoded rather than a config-center entry (`zaolang-platform-config`):
# small, rarely-changed number. Promote it there if it ever needs to be
# tunable per environment without a deploy.
MAX_ACTIVE_COLLABORATORS_PER_SERIES = 20

# Both an outstanding invite and an accepted membership occupy a "seat" —
# counting only `active` would let someone bypass the cap by leaving a pile
# of unanswered invites outstanding.
_COUNTS_TOWARD_LIMIT = (SeriesCollaboratorStatus.PENDING, SeriesCollaboratorStatus.ACTIVE)


def _get_drama_series(session: Session, series_id: str) -> Series:
    series = session.get(Series, series_id)
    if series is None or series.kind != SeriesKind.DRAMA:
        raise NotFound("剧集不存在。")
    return series


def is_active_member(session: Session, *, user_id: str, series_id: str) -> bool:
    """`True` for the owner, or a `status=active` collaborator. Anyone else
    (including a `pending`/`declined`/`removed` row) is not a member."""
    series = session.get(Series, series_id)
    if series is None:
        return False
    if series.owner_user_id == user_id:
        return True
    row = session.scalar(
        select(SeriesCollaborator.id).where(
            SeriesCollaborator.series_id == series_id,
            SeriesCollaborator.user_id == user_id,
            SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
        )
    )
    return row is not None


def collaborator_series_ids(session: Session, *, user_id: str) -> list[str]:
    """Series ids where `user_id` is an *active*, non-owner collaborator —
    feeds `editor_service.list_drama_series`'s owner-union-collaborator
    query."""
    return list(
        session.scalars(
            select(SeriesCollaborator.series_id).where(
                SeriesCollaborator.user_id == user_id,
                SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
            )
        )
    )


def active_members(session: Session, *, series_id: str) -> list[SeriesCollaborator]:
    """Active collaborators only — used to compute a series response's
    `is_collaboration`/`collaborator_count`."""
    return list(
        session.scalars(
            select(SeriesCollaborator).where(
                SeriesCollaborator.series_id == series_id,
                SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
            )
        )
    )


def active_member_counts(session: Session, *, series_ids: list[str]) -> dict[str, int]:
    """Batched `len(active_members(...))` per series id — avoids an N+1
    query when rendering a `GET /v1/drama-series` list response."""
    ids = list(dict.fromkeys(series_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(SeriesCollaborator.series_id, func.count())
        .where(
            SeriesCollaborator.series_id.in_(ids),
            SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
        )
        .group_by(SeriesCollaborator.series_id)
    )
    return dict(rows.tuples().all())


def profiles_by_user_id(session: Session, user_ids: list[str]) -> dict[str, Profile]:
    """Batch-loads `Profile` rows for a list of user ids — a small helper so
    API-layer response builders (collaborator lists, invite lists) don't
    each hand-roll the same query."""
    ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return {}
    return {
        profile.user_id: profile
        for profile in session.scalars(select(Profile).where(Profile.user_id.in_(ids)))
    }


def _find_profile_by_identifier(session: Session, identifier: str) -> Profile | None:
    """Resolves an invite target by either their `Profile.handle` or their
    registered `User.email` — mirrors the two identifiers a user already
    knows about themselves (handle shown on their own profile, email used to
    log in), so the inviter doesn't need a dedicated user-search endpoint.

    An "@" not at the very start is treated as an email (handles never
    contain one) rather than a handle typed with its leading "@" left on."""
    raw = identifier.strip()
    if "@" in raw and not raw.startswith("@"):
        user = session.scalar(select(User).where(func.lower(User.email) == raw.lower()))
        if user is None:
            return None
        return session.scalar(select(Profile).where(Profile.user_id == user.id))
    cleaned_handle = raw.lstrip("@")
    if not cleaned_handle:
        return None
    return session.scalar(select(Profile).where(Profile.handle == cleaned_handle))


def invite(
    session: Session, *, owner_user_id: str, series_id: str, identifier: str
) -> SeriesCollaborator:
    series = _get_drama_series(session, series_id)
    if series.owner_user_id != owner_user_id:
        raise NotFound("剧集不存在。")

    if not identifier.strip():
        raise ValidationFailed("请输入对方的昵称或注册邮箱。")
    profile = _find_profile_by_identifier(session, identifier)
    if profile is None:
        raise NotFound("找不到匹配的用户，请检查昵称或邮箱是否正确。")
    if profile.user_id == owner_user_id:
        raise ValidationFailed("不能邀请自己。")

    existing = session.scalar(
        select(SeriesCollaborator).where(
            SeriesCollaborator.series_id == series.id,
            SeriesCollaborator.user_id == profile.user_id,
        )
    )
    if existing is not None and existing.status == SeriesCollaboratorStatus.ACTIVE:
        raise Conflict("对方已经是该短剧的共创者。")
    if existing is not None and existing.status == SeriesCollaboratorStatus.PENDING:
        raise Conflict("已经邀请过对方，请等待对方确认。")

    active_count = session.scalar(
        select(func.count())
        .select_from(SeriesCollaborator)
        .where(
            SeriesCollaborator.series_id == series.id,
            SeriesCollaborator.status.in_(_COUNTS_TOWARD_LIMIT),
        )
    )
    if (active_count or 0) >= MAX_ACTIVE_COLLABORATORS_PER_SERIES:
        raise ValidationFailed(
            f"该短剧的共创人数已达上限（{MAX_ACTIVE_COLLABORATORS_PER_SERIES}人），"
            "请先移除后再邀请。"
        )

    if existing is None:
        collaborator = SeriesCollaborator(
            series_id=series.id,
            user_id=profile.user_id,
            invited_by_user_id=owner_user_id,
            status=SeriesCollaboratorStatus.PENDING,
        )
        session.add(collaborator)
    else:
        # Reuse a past declined/removed row rather than insert a duplicate —
        # the unique constraint on (series_id, user_id) means a second insert
        # would fail anyway, but reusing also keeps one stable id across a
        # user's re-invited history.
        collaborator = existing
        collaborator.status = SeriesCollaboratorStatus.PENDING
        collaborator.invited_by_user_id = owner_user_id
        collaborator.responded_at = None
    session.flush()

    inviter_profile = profiles_by_user_id(session, [owner_user_id]).get(owner_user_id)
    notify(
        session,
        user_id=profile.user_id,
        type=NotificationType.SERIES_COLLAB_INVITED,
        title_key="notification.series_collab_invited",
        payload={
            "series_id": series.id,
            "series_title": series.title,
            "collaborator_id": collaborator.id,
            "inviter_display_name": inviter_profile.display_name if inviter_profile else "",
        },
        target_type="series_collaboration",
        target_id=collaborator.id,
    )
    return collaborator


def list_members(session: Session, *, user_id: str, series_id: str) -> list[SeriesCollaborator]:
    series = _get_drama_series(session, series_id)
    if not is_active_member(session, user_id=user_id, series_id=series.id):
        raise NotFound("剧集不存在。")
    stmt = (
        select(SeriesCollaborator)
        .where(
            SeriesCollaborator.series_id == series.id,
            SeriesCollaborator.status.in_(
                (SeriesCollaboratorStatus.PENDING, SeriesCollaboratorStatus.ACTIVE)
            ),
        )
        .order_by(SeriesCollaborator.created_at.asc())
    )
    return list(session.scalars(stmt))


def remove(session: Session, *, actor_user_id: str, series_id: str, collaborator_id: str) -> None:
    """The owner may remove any row (kicking a `pending` invite or an
    `active` collaborator); a collaborator may only remove their own row
    (leaving). Anyone else is `Forbidden`."""
    series = _get_drama_series(session, series_id)
    collaborator = session.get(SeriesCollaborator, collaborator_id)
    if collaborator is None or collaborator.series_id != series.id:
        raise NotFound("协作记录不存在。")

    is_owner_action = actor_user_id == series.owner_user_id
    is_self_leave = actor_user_id == collaborator.user_id
    if not is_owner_action and not is_self_leave:
        raise Forbidden("没有权限移除该共创者。")
    if collaborator.status not in (
        SeriesCollaboratorStatus.PENDING,
        SeriesCollaboratorStatus.ACTIVE,
    ):
        raise Conflict("该共创关系已经结束。")

    collaborator.status = SeriesCollaboratorStatus.REMOVED
    collaborator.responded_at = utcnow()
    session.flush()

    notify_user_id = collaborator.user_id if is_owner_action else series.owner_user_id
    title_key = (
        "notification.series_collab_removed"
        if is_owner_action
        else "notification.series_collab_left"
    )
    actor_profile = profiles_by_user_id(session, [collaborator.user_id]).get(collaborator.user_id)
    notify(
        session,
        user_id=notify_user_id,
        type=NotificationType.SERIES_COLLAB_REMOVED,
        title_key=title_key,
        payload={
            "series_id": series.id,
            "series_title": series.title,
            "actor_display_name": actor_profile.display_name if actor_profile else "",
        },
        target_type="series_collaboration",
        target_id=collaborator.id,
    )


def list_my_invites(session: Session, *, user_id: str) -> list[SeriesCollaborator]:
    stmt = (
        select(SeriesCollaborator)
        .where(
            SeriesCollaborator.user_id == user_id,
            SeriesCollaborator.status == SeriesCollaboratorStatus.PENDING,
        )
        .order_by(SeriesCollaborator.created_at.desc())
    )
    return list(session.scalars(stmt))


def accept(session: Session, *, user_id: str, collaborator_id: str) -> SeriesCollaborator:
    collaborator = session.get(SeriesCollaborator, collaborator_id)
    if collaborator is None or collaborator.user_id != user_id:
        raise NotFound("邀请不存在。")
    if collaborator.status != SeriesCollaboratorStatus.PENDING:
        raise Conflict("该邀请已被处理。")
    collaborator.status = SeriesCollaboratorStatus.ACTIVE
    collaborator.responded_at = utcnow()
    session.flush()

    series = session.get(Series, collaborator.series_id)
    if series is not None:
        collaborator_profile = profiles_by_user_id(session, [user_id]).get(user_id)
        notify(
            session,
            user_id=series.owner_user_id,
            type=NotificationType.SERIES_COLLAB_ACCEPTED,
            title_key="notification.series_collab_accepted",
            payload={
                "series_id": series.id,
                "series_title": series.title,
                "collaborator_id": collaborator.id,
                "actor_display_name": collaborator_profile.display_name
                if collaborator_profile
                else "",
            },
            target_type="series_collaboration",
            target_id=collaborator.id,
        )
    return collaborator


def decline(session: Session, *, user_id: str, collaborator_id: str) -> SeriesCollaborator:
    collaborator = session.get(SeriesCollaborator, collaborator_id)
    if collaborator is None or collaborator.user_id != user_id:
        raise NotFound("邀请不存在。")
    if collaborator.status != SeriesCollaboratorStatus.PENDING:
        raise Conflict("该邀请已被处理。")
    collaborator.status = SeriesCollaboratorStatus.DECLINED
    collaborator.responded_at = utcnow()
    session.flush()
    return collaborator
