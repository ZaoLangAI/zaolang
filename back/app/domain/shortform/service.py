"""Short-video delivery specs and distribution intents.

The specs themselves live in the config centre, so nothing here hard-codes a
number that a destination app may change next quarter.

This module always creates the intent and hands back the material to post
with — `EXPORTED`/`READY`, never `SUBMITTED`/`FAILED`. Advancing an intent
into those two states, by actually calling a connected platform's API, is
`app.domain.distribution.service.publish_fanout`'s job (`mark_submitted`/
`mark_failed` below are its write path into this same row); a channel with no
configured/linked account still stops here exactly as before.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.media import service as media_service
from app.models import PublicationIntent, Work, WorkVersion
from app.models.base import utcnow
from app.models.enums import LifecycleStatus, PublicationStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import ShortformConfig, ShortformProfile


@dataclass(slots=True)
class PublicationBundle:
    intent: PublicationIntent
    download_url: str | None


def catalog(session: Session) -> ShortformConfig:
    return config_service.get_typed(session, "shortform", ShortformConfig)


def resolve_profile(session: Session, key: str | None) -> tuple[str, ShortformProfile]:
    """Looks a spec up by name, falling back to the configured default."""
    config = catalog(session)
    resolved = key or config.default_profile
    profile = config.profiles.get(resolved)
    if profile is None:
        raise ValidationFailed(
            f"未知的短视频规格: {resolved}",
            fields={"shortform_profile": "规格不存在"},
            available=sorted(config.profiles),
        )
    return resolved, profile


def assert_params_consistent(session: Session, params: Mapping[str, Any]) -> None:
    """Refuses a job whose parameters contradict the spec it claims to follow.

    Without this the studio could submit 16:9 under a vertical profile and the
    mismatch would only surface once the user had already paid for the clip.
    """
    key = params.get("shortform_profile")
    if not key:
        return

    profile_key, profile = resolve_profile(session, str(key))

    aspect_ratio = str(params.get("aspect_ratio") or "未指定")
    if aspect_ratio != profile.aspect_ratio:
        raise ValidationFailed(
            f"{profile_key} 规格要求 {profile.aspect_ratio} 画幅，当前为 {aspect_ratio}。",
            fields={"params.aspect_ratio": f"必须为 {profile.aspect_ratio}"},
        )

    duration = int(params.get("duration_seconds") or 0)
    if not profile.min_duration_seconds <= duration <= profile.max_duration_seconds:
        raise ValidationFailed(
            f"{profile_key} 规格要求时长在 {profile.min_duration_seconds}-"
            f"{profile.max_duration_seconds} 秒之间。",
            fields={
                "params.duration_seconds": (
                    f"必须在 {profile.min_duration_seconds}-{profile.max_duration_seconds} 秒之间"
                )
            },
        )


def create_publication_intent(
    session: Session,
    *,
    user_id: str,
    work_id: str,
    channel: str,
    title: str,
    description: str | None,
    hashtags: Sequence[str],
    cover_asset_id: str | None = None,
    scheduled_at: dt.datetime | None = None,
) -> PublicationBundle:
    """Records an export and hands back the material to post with.

    The status reflects what actually happened here: `EXPORTED` once a
    download URL exists, `READY` when the work has no deliverable yet.
    `SUBMITTED`/`FAILED` are only ever set afterwards, by `mark_submitted`/
    `mark_failed` below, once a caller has actually pushed this same intent
    to a real platform.
    """
    work, version = _owned_work(session, work_id=work_id, user_id=user_id)

    output_asset_id = version.primary_output_asset_id
    download_url = _download_url(session, asset_id=output_asset_id, user_id=user_id)

    intent = PublicationIntent(
        work_id=work.id,
        user_id=user_id,
        channel=channel,
        status=PublicationStatus.EXPORTED if download_url else PublicationStatus.READY,
        payload_json={
            "title": title,
            "description": description,
            "hashtags": list(hashtags),
            "cover_asset_id": cover_asset_id or version.cover_asset_id,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        },
    )
    session.add(intent)
    session.flush()
    return PublicationBundle(intent=intent, download_url=download_url)


def list_publication_intents(
    session: Session, *, user_id: str, work_id: str, limit: int = 50
) -> list[PublicationIntent]:
    _owned_work(session, work_id=work_id, user_id=user_id)
    return list(
        session.scalars(
            select(PublicationIntent)
            .where(PublicationIntent.work_id == work_id)
            .order_by(PublicationIntent.created_at.desc())
            .limit(limit)
        )
    )


def mark_submitted(
    session: Session, intent: PublicationIntent, *, external_post_id: str | None
) -> PublicationIntent:
    """Advances an intent once `app.domain.distribution.service` actually
    pushed it to a real platform and got a post id back."""
    intent.status = PublicationStatus.SUBMITTED
    intent.external_post_id = external_post_id
    intent.submitted_at = utcnow()
    session.flush()
    return intent


def mark_failed(session: Session, intent: PublicationIntent) -> PublicationIntent:
    """Counterpart to `mark_submitted` for a real platform push that failed."""
    intent.status = PublicationStatus.FAILED
    session.flush()
    return intent


# --- internals -----------------------------------------------------------


def _owned_work(session: Session, *, work_id: str, user_id: str) -> tuple[Work, WorkVersion]:
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("只能分发自己的作品。")
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        raise Conflict("该作品已下架，不能再分发。")

    version = session.get(WorkVersion, work.current_version_id or "")
    if version is None:
        raise Conflict("作品没有可用版本。")
    return work, version


def _download_url(session: Session, *, asset_id: str | None, user_id: str) -> str | None:
    if not asset_id:
        return None
    return media_service.signed_url_for(session, asset_id=asset_id, viewer_user_id=user_id)
