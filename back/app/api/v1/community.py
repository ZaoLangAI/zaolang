"""Collections, style presets, notifications, follows and reports."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.api.schemas.common import CountResponse, OkResponse, Page
from app.api.schemas.jobs import NotificationResponse, ReportCreateRequest
from app.api.schemas.works import (
    AuthorSummary,
    CollectionCreateRequest,
    CollectionResponse,
    CollectionUpdateRequest,
    StylePresetCreateRequest,
    StylePresetResponse,
)
from app.domain.access import service as access_service
from app.domain.errors import Conflict, Forbidden, NotFound
from app.domain.notifications import push as notifications
from app.models import (
    Collection,
    CollectionItem,
    EditorExport,
    Follow,
    GenerationJob,
    Notification,
    Profile,
    ReportCase,
    StylePreset,
    Work,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import NotificationType
from app.presenters import media_urls
from app.realtime import publisher

router = APIRouter(tags=["community"])

NOTIFICATION_STREAM_HEARTBEAT_SECONDS = 15
NOTIFICATION_STREAM_MAX_DURATION_SECONDS = 600


# --- collections ---------------------------------------------------------


@router.post("/collections", response_model=CollectionResponse, status_code=201)
def create_collection(
    payload: CollectionCreateRequest, user: CurrentUser, session: DbSession
) -> CollectionResponse:
    collection = Collection(
        owner_user_id=user.id,
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
    )
    session.add(collection)
    session.commit()
    return _collection_response(session, collection)


@router.get("/collections", response_model=Page[CollectionResponse])
def list_collections(user: CurrentUser, session: DbSession) -> Page[CollectionResponse]:
    rows = session.scalars(
        select(Collection)
        .where(Collection.owner_user_id == user.id)
        .order_by(Collection.created_at.desc())
    )
    return Page(items=[_collection_response(session, c) for c in rows])


@router.patch("/collections/{collection_id}", response_model=CollectionResponse)
def update_collection(
    collection_id: str, payload: CollectionUpdateRequest, user: CurrentUser, session: DbSession
) -> CollectionResponse:
    collection = _owned_collection(session, collection_id, user.id)
    collection.name = payload.name
    collection.description = payload.description
    collection.is_public = payload.is_public
    session.commit()
    return _collection_response(session, collection)


@router.delete("/collections/{collection_id}", response_model=OkResponse)
def delete_collection(collection_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    collection = _owned_collection(session, collection_id, user.id)
    # `collection_items.collection_id` is `ondelete="CASCADE"`, so the items
    # disappear with the row — no need to delete them one by one here.
    session.delete(collection)
    session.commit()
    return OkResponse()


@router.post("/collections/{collection_id}/items", response_model=OkResponse)
def add_to_collection(
    collection_id: str, work_id: str, user: CurrentUser, session: DbSession
) -> OkResponse:
    collection = _owned_collection(session, collection_id, user.id)
    if session.get(Work, work_id) is None:
        raise NotFound("作品不存在。")

    existing = session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == collection.id, CollectionItem.work_id == work_id
        )
    )
    if existing is None:
        position = (
            session.scalar(
                select(func.count())
                .select_from(CollectionItem)
                .where(CollectionItem.collection_id == collection.id)
            )
            or 0
        )
        session.add(CollectionItem(collection_id=collection.id, work_id=work_id, position=position))
        session.commit()
    return OkResponse()


@router.delete("/collections/{collection_id}/items/{work_id}", response_model=OkResponse)
def remove_from_collection(
    collection_id: str, work_id: str, user: CurrentUser, session: DbSession
) -> OkResponse:
    _owned_collection(session, collection_id, user.id)
    item = session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == collection_id, CollectionItem.work_id == work_id
        )
    )
    if item is not None:
        session.delete(item)
        session.commit()
    return OkResponse()


# --- style presets -------------------------------------------------------


@router.post("/style-presets", response_model=StylePresetResponse, status_code=201)
def create_preset(
    payload: StylePresetCreateRequest, user: CurrentUser, session: DbSession
) -> StylePresetResponse:
    """Saves reusable parameters.

    A preset derived from someone else's work only stores parameters the source
    licence actually exposed, so it cannot leak a private prompt.
    """
    if payload.derived_from_work_version_id:
        version = session.get(WorkVersion, payload.derived_from_work_version_id)
        if version is None:
            raise NotFound("来源版本不存在。")
        work = session.get(Work, version.work_id)
        if work is not None and work.owner_user_id != user.id:
            if not version.reusable_params_json:
                raise Forbidden("该作品未开放参数复用。")
            if not access_service.viewer_unlocked_work(session, work, user.id):
                raise Forbidden("该作品未开放参数复用。")

    preset = StylePreset(
        owner_user_id=user.id,
        name=payload.name,
        description=payload.description,
        params_json=payload.params,
        derived_from_work_version_id=payload.derived_from_work_version_id,
        is_public=payload.is_public,
    )
    session.add(preset)
    session.commit()
    return _preset_response(session, preset)


@router.get("/style-presets", response_model=Page[StylePresetResponse])
def list_presets(
    session: DbSession,
    viewer: OptionalUser,
    mine: bool = False,
    limit: int = Query(default=30, ge=1, le=60),
) -> Page[StylePresetResponse]:
    stmt = select(StylePreset).order_by(StylePreset.apply_count.desc()).limit(limit)
    if mine:
        if viewer is None:
            raise Forbidden("请先登录。")
        stmt = stmt.where(StylePreset.owner_user_id == viewer.id)
    else:
        stmt = stmt.where(StylePreset.is_public.is_(True))
    return Page(items=[_preset_response(session, p) for p in session.scalars(stmt)])


@router.post("/style-presets/{preset_id}/apply", response_model=StylePresetResponse)
def apply_preset(preset_id: str, user: CurrentUser, session: DbSession) -> StylePresetResponse:
    preset = session.get(StylePreset, preset_id)
    if preset is None:
        raise NotFound("预设不存在。")
    if not preset.is_public and preset.owner_user_id != user.id:
        raise Forbidden("该预设未公开。")

    preset.apply_count += 1
    session.commit()
    return _preset_response(session, preset)


# --- notifications -------------------------------------------------------


@router.get("/notifications", response_model=Page[NotificationResponse])
def list_notifications(
    user: CurrentUser,
    session: DbSession,
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=60),
) -> Page[NotificationResponse]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.updated_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    rows = list(session.scalars(stmt))
    job_ids = [n.target_id for n in rows if n.target_type == "generation_job" and n.target_id]
    export_ids = [n.target_id for n in rows if n.target_type == "editor_export" and n.target_id]
    jobs = (
        {
            job.id: job
            for job in session.scalars(select(GenerationJob).where(GenerationJob.id.in_(job_ids)))
        }
        if job_ids
        else {}
    )
    exports = (
        {
            export.id: export
            for export in session.scalars(
                select(EditorExport).where(EditorExport.id.in_(export_ids))
            )
        }
        if export_ids
        else {}
    )

    return Page(
        items=[_notification_response(session, n, jobs=jobs, exports=exports) for n in rows]
    )


@router.get("/notifications/unread-count", response_model=CountResponse)
def unread_count(user: CurrentUser, session: DbSession) -> CountResponse:
    count = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return CountResponse(count=int(count or 0))


@router.post("/notifications/read", response_model=CountResponse)
def mark_read(
    user: CurrentUser, session: DbSession, notification_id: str | None = None
) -> CountResponse:
    stmt = select(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )
    if notification_id:
        stmt = stmt.where(Notification.id == notification_id)

    marked = 0
    now = utcnow()
    for notification in session.scalars(stmt):
        notification.read_at = now
        marked += 1
    session.commit()
    return CountResponse(count=marked)


@router.get("/notifications/stream")
def stream_notifications(user: CurrentUser) -> StreamingResponse:
    """Live tail of this user's notifications, for the bell badge/popover and
    the right-side creation-status toasts.

    Unlike `/generation-jobs/{id}/events`, there is no `Last-Event-ID` backfill
    here: `GET /notifications` already covers "current state on load," so this
    stream only has to carry the live tail. That also means the generator below
    must never touch `session` — it is request-scoped and already closed by the
    time a `StreamingResponse` generator body runs; everything it needs comes
    from `publisher.subscribe_notifications`, which is pure Redis.
    """

    def generate() -> Iterator[str]:
        started = time.monotonic()
        last_heartbeat = started
        for payload in publisher.subscribe_notifications(user.id):
            if time.monotonic() - started > NOTIFICATION_STREAM_MAX_DURATION_SECONDS:
                break
            if not payload:
                if time.monotonic() - last_heartbeat > NOTIFICATION_STREAM_HEARTBEAT_SECONDS:
                    last_heartbeat = time.monotonic()
                    yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


# --- social --------------------------------------------------------------


@router.post("/users/{user_id}/follow", response_model=OkResponse)
def follow(user_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    if user_id == user.id:
        raise Conflict("不能关注自己。")
    if session.scalar(select(Profile).where(Profile.user_id == user_id)) is None:
        raise NotFound("用户不存在。")

    existing = session.scalar(
        select(Follow).where(Follow.follower_user_id == user.id, Follow.followed_user_id == user_id)
    )
    if existing is None:
        session.add(Follow(follower_user_id=user.id, followed_user_id=user_id))
        follower = session.scalar(select(Profile).where(Profile.user_id == user.id))
        notifications.notify(
            session,
            user_id=user_id,
            type=NotificationType.NEW_FOLLOWER,
            title_key="notification.new_follower",
            payload={
                "follower_user_id": user.id,
                "follower_handle": follower.handle if follower else "",
                "follower_display_name": follower.display_name if follower else "",
            },
            target_type="user",
            target_id=user.id,
        )
        session.commit()
    return OkResponse()


@router.delete("/users/{user_id}/follow", response_model=OkResponse)
def unfollow(user_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    existing = session.scalar(
        select(Follow).where(Follow.follower_user_id == user.id, Follow.followed_user_id == user_id)
    )
    if existing is not None:
        session.delete(existing)
        session.commit()
    return OkResponse()


@router.post("/reports", response_model=OkResponse, status_code=201)
def create_report(
    payload: ReportCreateRequest, user: CurrentUser, session: DbSession
) -> OkResponse:
    session.add(
        ReportCase(
            reporter_user_id=user.id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            reason=payload.reason,
            detail=payload.detail,
        )
    )
    session.commit()
    return OkResponse()


# --- projections ---------------------------------------------------------


def _owned_collection(session, collection_id: str, user_id: str) -> Collection:  # type: ignore[no-untyped-def]
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise NotFound("作品集不存在。")
    if collection.owner_user_id != user_id:
        raise Forbidden("不能修改他人的作品集。")
    return collection


def _collection_response(session, collection: Collection) -> CollectionResponse:  # type: ignore[no-untyped-def]
    items = list(
        session.scalars(
            select(CollectionItem)
            .where(CollectionItem.collection_id == collection.id)
            .order_by(CollectionItem.position)
            .limit(4)
        )
    )
    covers: list[str] = []
    for item in items:
        work = session.get(Work, item.work_id)
        if work is None or not work.current_version_id:
            continue
        version = session.get(WorkVersion, work.current_version_id)
        url = media_urls.asset_url(session, version.cover_asset_id) if version else None
        if url:
            covers.append(url)

    total = session.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .where(CollectionItem.collection_id == collection.id)
    )
    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        is_public=collection.is_public,
        item_count=int(total or 0),
        cover_urls=covers,
    )


def _notification_response(
    session: Session,
    record: Notification,
    *,
    jobs: dict[str, GenerationJob],
    exports: dict[str, EditorExport],
) -> NotificationResponse:
    ntype, title_key, payload = notifications.present_notification(
        session, record, jobs=jobs, exports=exports
    )
    return NotificationResponse(
        id=record.id,
        type=ntype,
        title_key=title_key,
        payload=payload,
        target_type=record.target_type,
        target_id=record.target_id,
        read=record.read_at is not None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _preset_response(session, preset: StylePreset) -> StylePresetResponse:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(Profile).where(Profile.user_id == preset.owner_user_id))
    owner = (
        AuthorSummary(
            user_id=preset.owner_user_id,
            display_name=profile.display_name,
            handle=profile.handle,
            avatar_url=media_urls.asset_url(session, profile.avatar_asset_id),
        )
        if profile
        else None
    )
    return StylePresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        params=preset.params_json,
        is_public=preset.is_public,
        apply_count=preset.apply_count,
        owner=owner,
    )
