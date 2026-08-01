"""Configuration centre: read, edit, diff, roll back, feature flags, announcements."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AnnouncementRequest,
    AnnouncementView,
    AuditLogView,
    ConfigDiffEntry,
    ConfigDiffResponse,
    ConfigRollbackRequest,
    ConfigUpdateRequest,
    ConfigValueResponse,
    ConfigVersionView,
    FeatureFlagView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    Admin,
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import NotFound
from app.models import Announcement, Notification, PlatformConfig, User
from app.models.base import utcnow
from app.models.enums import NotificationType, UserStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import CONFIG_SCHEMAS, DEFAULT_CONFIGS, FeatureFlags

router = APIRouter(tags=["admin:config"])

FLAG_DESCRIPTIONS = {
    "semantic_search": "语义检索与相似作品推荐",
    "style_presets": "风格预设库",
    "royalties": "二创回流分成",
    "command_palette": "Cmd+K 命令面板",
    "video_generation": "视频生成能力",
    "public_registration": "开放注册",
}


@router.get("/config", response_model=Page[ConfigValueResponse])
def list_config(session: DbSession, user: Viewer, _: AdminRead) -> Page[ConfigValueResponse]:
    return Page(items=[_value_response(session, key) for key in config_service.all_keys()])


@router.get("/config/{key}", response_model=ConfigValueResponse)
def get_config(key: str, session: DbSession, user: Viewer, _: AdminRead) -> ConfigValueResponse:
    _assert_known(key)
    return _value_response(session, key)


@router.put("/config/{key}", response_model=ConfigValueResponse)
def update_config(
    key: str,
    payload: ConfigUpdateRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminWrite,
) -> ConfigValueResponse:
    """Validates, versions and activates a new value.

    Validation happens before the write, so an invalid weight is rejected at
    edit time rather than surfacing later inside a worker.
    """
    _assert_known(key)
    before = config_service.get_raw(session, key)
    row = config_service.set_value(
        session, key, payload.value, actor_user_id=user.id, note=payload.note
    )
    audit.record(
        session,
        actor=user,
        action="config.update",
        target_type="platform_config",
        target_id=key,
        before=before,
        after=dict(row.value_json),
        reason=payload.note,
        request=request,
    )
    session.commit()
    return _value_response(session, key)


@router.get("/config/{key}/history", response_model=Page[ConfigVersionView])
def config_history(
    key: str,
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    limit: int = Query(default=20, ge=1, le=100),
) -> Page[ConfigVersionView]:
    _assert_known(key)
    rows = config_service.history(session, key, limit=limit)
    return Page(items=[ConfigVersionView.model_validate(r) for r in rows])


@router.get("/config/{key}/diff", response_model=ConfigDiffResponse)
def config_diff(
    key: str,
    from_version: int,
    to_version: int,
    session: DbSession,
    user: Viewer,
    _: AdminRead,
) -> ConfigDiffResponse:
    """Flattened field-by-field comparison of two versions."""
    _assert_known(key)
    left = _version_value(session, key, from_version)
    right = _version_value(session, key, to_version)

    flat_left = _flatten(left)
    flat_right = _flatten(right)
    entries = [
        ConfigDiffEntry(path=path, before=flat_left.get(path), after=flat_right.get(path))
        for path in sorted(set(flat_left) | set(flat_right))
        if flat_left.get(path) != flat_right.get(path)
    ]
    return ConfigDiffResponse(
        key=key, from_version=from_version, to_version=to_version, entries=entries
    )


@router.post("/config/{key}/rollback", response_model=ConfigValueResponse)
def rollback_config(
    key: str,
    payload: ConfigRollbackRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> ConfigValueResponse:
    """Re-applies an earlier version as a new one.

    Moving forward to a copy keeps both the mistake and its correction in the
    history, which is what the audit trail is for.
    """
    require_confirmation(payload.confirm)
    _assert_known(key)
    before = config_service.get_raw(session, key)
    row = config_service.rollback(session, key, payload.target_version, actor_user_id=user.id)
    audit.record(
        session,
        actor=user,
        action="config.rollback",
        target_type="platform_config",
        target_id=key,
        before=before,
        after=dict(row.value_json),
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _value_response(session, key)


@router.get("/feature-flags", response_model=Page[FeatureFlagView])
def feature_flags(session: DbSession, user: Viewer, _: AdminRead) -> Page[FeatureFlagView]:
    flags = config_service.get_typed(session, "feature_flags", FeatureFlags)
    items = [
        FeatureFlagView(
            name=name,
            enabled=bool(getattr(flags, name)),
            rollout_percent=flags.rollout_percentages.get(name, 100),
            description=FLAG_DESCRIPTIONS.get(name, ""),
        )
        for name in FLAG_DESCRIPTIONS
    ]
    return Page(items=items)


@router.get("/audit-logs", response_model=Page[AuditLogView])
def audit_logs(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    actor_user_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AuditLogView]:
    rows = audit.search(
        session,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        cursor=cursor,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[AuditLogView.model_validate(r) for r in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.post("/announcements", response_model=AnnouncementView, status_code=201)
def create_announcement(
    payload: AnnouncementRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> AnnouncementView:
    """Publishes a notice, optionally fanning it out as in-app notifications."""
    announcement = Announcement(
        kind=payload.kind,
        title_zh=payload.title_zh,
        title_en=payload.title_en,
        body_zh=payload.body_zh,
        body_en=payload.body_en,
        starts_at=payload.starts_at or utcnow(),
        ends_at=payload.ends_at,
        is_published=payload.is_published,
        created_by_user_id=user.id,
    )
    session.add(announcement)
    session.flush()

    if payload.broadcast and payload.is_published:
        _broadcast(session, announcement)

    audit.record(
        session,
        actor=user,
        action="announcement.create",
        target_type="announcement",
        target_id=announcement.id,
        after={"kind": announcement.kind, "published": announcement.is_published},
        request=request,
    )
    session.commit()
    return AnnouncementView.model_validate(announcement)


@router.get("/announcements", response_model=Page[AnnouncementView])
def list_announcements(session: DbSession, user: Viewer, _: AdminRead) -> Page[AnnouncementView]:
    rows = session.scalars(select(Announcement).order_by(Announcement.starts_at.desc()))
    return Page(items=[AnnouncementView.model_validate(a) for a in rows])


def _assert_known(key: str) -> None:
    if key not in CONFIG_SCHEMAS:
        raise NotFound(f"未知的配置键: {key}")


def _value_response(session, key: str) -> ConfigValueResponse:  # type: ignore[no-untyped-def]
    row = session.scalar(
        select(PlatformConfig).where(PlatformConfig.key == key, PlatformConfig.is_active.is_(True))
    )
    return ConfigValueResponse(
        key=key,
        version=row.version if row else 0,
        value=dict(row.value_json) if row else dict(DEFAULT_CONFIGS[key]),
        schema_fields=sorted(CONFIG_SCHEMAS[key].model_fields),
    )


def _version_value(session, key: str, version: int) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if version == 0:
        return dict(DEFAULT_CONFIGS[key])
    row = session.scalar(
        select(PlatformConfig).where(PlatformConfig.key == key, PlatformConfig.version == version)
    )
    if row is None:
        raise NotFound(f"配置 {key} 不存在版本 {version}。")
    return dict(row.value_json)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Dotted paths so a nested change shows up as one readable row."""
    if isinstance(value, dict):
        flat: dict[str, Any] = {}
        for k, v in value.items():
            flat.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return flat
    return {prefix or "(root)": value}


def _broadcast(session, announcement: Announcement) -> None:  # type: ignore[no-untyped-def]
    recipients = session.scalars(select(User.id).where(User.status == UserStatus.ACTIVE))
    for user_id in recipients:
        session.add(
            Notification(
                user_id=user_id,
                type=NotificationType.SYSTEM,
                title_key="notification.announcement",
                payload_json={
                    "announcement_id": announcement.id,
                    "kind": announcement.kind,
                },
                target_type="announcement",
                target_id=announcement.id,
            )
        )
