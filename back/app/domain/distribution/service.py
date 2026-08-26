"""Connect/callback/list/disconnect + one-click fan-out publish.

This module is the only thing in the codebase that talks to a `PlatformClient`
directly — everything else (the API layer, other domains) goes through the
functions here, never `DouyinClient`/`KuaishouClient` themselves. That keeps
the `{channel: PlatformClient}` registry the single place a TikTok/Xiaohongshu
implementation would be added later.

Fan-out publishing never lets one bad channel fail the whole request: a
channel with no configured app credentials, or no linked account, is recorded
as a skipped manual-style intent (same as today's `MANUAL_DOWNLOAD` path)
rather than raising, and a channel whose real publish call fails marks that
one `PublicationIntent` `FAILED` without touching the others.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.distribution import crypto
from app.domain.distribution.client_base import PlatformClient
from app.domain.distribution.douyin_client import DouyinClient
from app.domain.distribution.kuaishou_client import KuaishouClient
from app.domain.errors import (
    DomainError,
    Forbidden,
    NotFound,
    PlatformOAuthFailed,
    PlatformPublishFailed,
    ValidationFailed,
)
from app.domain.shortform import service as shortform_service
from app.models import (
    Asset,
    EpisodeExternalMetric,
    PlatformAccountLink,
    PublicationIntent,
    Work,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import DistributionChannel, PlatformAccountLinkStatus, PublicationStatus
from app.storage import s3

# A stale or replayed OAuth callback is rejected past this age.
STATE_TTL_SECONDS = 600

_CLIENTS: dict[str, PlatformClient] = {
    DistributionChannel.DOUYIN.value: DouyinClient(),
    DistributionChannel.KUAISHOU.value: KuaishouClient(),
}


@dataclass(slots=True)
class PublicationResult:
    """One channel's outcome from `publish_fanout`."""

    channel: str
    status: str
    external_post_id: str | None = None
    error: str | None = None
    # Set only for a channel that was skipped rather than attempted, e.g.
    # "manual_download", "not_configured", "not_linked".
    reason: str | None = None


def config_status() -> dict[str, bool]:
    """`{channel: bool}` — true iff that channel's AppKey/AppSecret are both set."""
    settings = get_settings()
    return {
        DistributionChannel.DOUYIN.value: bool(
            settings.douyin_app_key and settings.douyin_app_secret
        ),
        DistributionChannel.KUAISHOU.value: bool(
            settings.kuaishou_app_id and settings.kuaishou_app_secret
        ),
    }


def connect_start(session: Session, *, user_id: str, channel: str) -> str:
    """Returns the authorize URL a creator is redirected to.

    Session is unused today (no DB write happens before the redirect) but
    kept in the signature for symmetry with the other functions here and in
    case a future revision wants to record the connect attempt.
    """
    _ = session
    client = _client_for(channel)
    state = _sign_state(user_id=user_id, channel=channel)
    return client.authorize_url(state)


def connect_callback(
    session: Session, *, channel: str, code: str, state: str
) -> PlatformAccountLink:
    """Verifies `state`, exchanges `code`, and upserts the `PlatformAccountLink`.

    The state check happens before any other work — an invalid or stale state
    is rejected before the code is ever exchanged.
    """
    user_id = _verify_state(state, expected_channel=channel)
    client = _client_for(channel)
    tokens = client.exchange_code(code)

    expires_at = (
        utcnow() + dt.timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    )
    access_token_encrypted = crypto.encrypt_token(tokens.access_token)
    refresh_token_encrypted = (
        crypto.encrypt_token(tokens.refresh_token) if tokens.refresh_token else None
    )

    existing = session.scalar(
        select(PlatformAccountLink).where(
            PlatformAccountLink.user_id == user_id,
            PlatformAccountLink.channel == channel,
            PlatformAccountLink.external_account_id == tokens.open_id,
        )
    )
    if existing is not None:
        existing.access_token_encrypted = access_token_encrypted
        existing.refresh_token_encrypted = refresh_token_encrypted
        existing.token_expires_at = expires_at
        existing.status = PlatformAccountLinkStatus.ACTIVE
        existing.revoked_at = None
        existing.last_refreshed_at = utcnow()
        session.flush()
        return existing

    link = PlatformAccountLink(
        user_id=user_id,
        channel=channel,
        external_account_id=tokens.open_id,
        access_token_encrypted=access_token_encrypted,
        refresh_token_encrypted=refresh_token_encrypted,
        token_expires_at=expires_at,
        scopes_json=[],
        status=PlatformAccountLinkStatus.ACTIVE,
    )
    session.add(link)
    session.flush()
    return link


def list_linked_accounts(session: Session, *, user_id: str) -> list[PlatformAccountLink]:
    return list(
        session.scalars(
            select(PlatformAccountLink)
            .where(
                PlatformAccountLink.user_id == user_id,
                PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
            )
            .order_by(PlatformAccountLink.connected_at.desc())
        )
    )


def list_metrics_for_work(session: Session, *, user_id: str, work_id: str) -> list[EpisodeExternalMetric]:
    """Every channel's latest pulled snapshot for one work, ownership-checked.

    Read-only — the pull itself only ever happens on `pull_episode_metrics`'s
    own beat schedule, never synchronously in a request.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("只能查看自己作品的数据。")
    return list(
        session.scalars(
            select(EpisodeExternalMetric)
            .where(EpisodeExternalMetric.work_id == work_id)
            .order_by(EpisodeExternalMetric.channel.asc())
        )
    )


def disconnect(session: Session, *, user_id: str, link_id: str) -> PlatformAccountLink:
    """Tombstones the link (`status=revoked`) — never a hard delete."""
    link = session.get(PlatformAccountLink, link_id)
    if link is None:
        raise NotFound("未找到该平台账号连接。")
    if link.user_id != user_id:
        raise Forbidden("不能操作他人的平台账号连接。")
    link.status = PlatformAccountLinkStatus.REVOKED
    link.revoked_at = utcnow()
    session.flush()
    return link


def publish_fanout(
    session: Session,
    *,
    user_id: str,
    work_id: str,
    channels: Sequence[str],
    title: str,
    description: str | None,
    hashtags: Sequence[str],
) -> list[PublicationResult]:
    """One `PublicationIntent` per requested channel, real-pushed where possible.

    Ownership of `work_id` is checked once per channel by
    `shortform_service.create_publication_intent` (via its own `_owned_work`)
    — the same helper the existing single-channel publish route already
    relies on, so a work belonging to another user 404s/403s exactly as it
    does there, before any platform call is attempted.
    """
    results: list[PublicationResult] = []
    for channel in channels:
        bundle = shortform_service.create_publication_intent(
            session,
            user_id=user_id,
            work_id=work_id,
            channel=channel,
            title=title,
            description=description,
            hashtags=hashtags,
        )
        intent = bundle.intent

        if channel == DistributionChannel.MANUAL_DOWNLOAD.value:
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="manual_download")
            )
            continue

        client = _CLIENTS.get(channel)
        if client is None or not config_status().get(channel, False):
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="not_configured")
            )
            continue

        link = _active_link(session, user_id=user_id, channel=channel)
        if link is None:
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="not_linked")
            )
            continue

        try:
            _push_to_platform(
                session,
                client=client,
                link=link,
                intent=intent,
                title=title,
                description=description,
                hashtags=hashtags,
            )
            results.append(
                PublicationResult(
                    channel=channel,
                    status=intent.status,
                    external_post_id=intent.external_post_id,
                )
            )
        except DomainError as exc:
            shortform_service.mark_failed(session, intent)
            results.append(
                PublicationResult(channel=channel, status=intent.status, error=exc.message)
            )

    session.flush()
    return results


def pull_episode_metrics(session: Session) -> int:
    """Refreshes `EpisodeExternalMetric` for every submitted post still on a
    real platform channel — called from `app.workers.tasks.pull_episode_metrics`
    on its own beat schedule, never synchronously from a request.

    One post's failure (an expired token, a transient network error) is
    logged into nothing and simply skipped — it never stops the sweep from
    reaching the next post, and next run's pull tries it again.
    """
    intents = list(
        session.scalars(
            select(PublicationIntent).where(
                PublicationIntent.status == PublicationStatus.SUBMITTED,
                PublicationIntent.channel.in_(
                    [DistributionChannel.DOUYIN.value, DistributionChannel.KUAISHOU.value]
                ),
                PublicationIntent.external_post_id.is_not(None),
            )
        )
    )
    pulled = 0
    for intent in intents:
        client = _CLIENTS.get(intent.channel)
        if client is None:
            continue
        link = _active_link(session, user_id=intent.user_id, channel=intent.channel)
        if link is None:
            continue
        try:
            access_token = crypto.decrypt_token(link.access_token_encrypted)
            snapshot = client.fetch_metrics(
                access_token, link.external_account_id, intent.external_post_id or ""
            )
        except DomainError:
            continue

        existing = session.scalar(
            select(EpisodeExternalMetric).where(
                EpisodeExternalMetric.work_id == intent.work_id,
                EpisodeExternalMetric.channel == intent.channel,
                EpisodeExternalMetric.external_post_id == intent.external_post_id,
            )
        )
        if existing is None:
            existing = EpisodeExternalMetric(
                work_id=intent.work_id,
                channel=intent.channel,
                external_post_id=intent.external_post_id,
            )
            session.add(existing)
        existing.view_count = snapshot.view_count
        existing.like_count = snapshot.like_count
        existing.comment_count = snapshot.comment_count
        existing.share_count = snapshot.share_count
        existing.fetched_at = utcnow()
        pulled += 1

    session.commit()
    return pulled


# --- internals -------------------------------------------------------------


def _push_to_platform(
    session: Session,
    *,
    client: PlatformClient,
    link: PlatformAccountLink,
    intent: PublicationIntent,
    title: str,
    description: str | None,
    hashtags: Sequence[str],
) -> None:
    file_bytes = _asset_bytes_for_work(session, intent.work_id)
    if not file_bytes:
        raise PlatformPublishFailed("作品没有可用的成片文件。")

    # Decrypted only for the lifetime of this call — never persisted, never
    # logged, never put in an exception message.
    access_token = crypto.decrypt_token(link.access_token_encrypted)
    ticket = client.init_upload(access_token)
    video_id = client.upload_video(ticket, file_bytes)
    caption = _compose_caption(title, description, hashtags)
    result = client.create_post(access_token, link.external_account_id, video_id, caption)
    shortform_service.mark_submitted(
        session, intent, external_post_id=result.item_id or result.video_id
    )


def _compose_caption(title: str, description: str | None, hashtags: Sequence[str]) -> str:
    parts = [title]
    if description:
        parts.append(description)
    if hashtags:
        parts.append(" ".join(f"#{tag}" for tag in hashtags))
    return "\n".join(part for part in parts if part)


def _asset_bytes_for_work(session: Session, work_id: str) -> bytes | None:
    work = session.get(Work, work_id)
    if work is None or not work.current_version_id:
        return None
    version = session.get(WorkVersion, work.current_version_id)
    if version is None or not version.primary_output_asset_id:
        return None
    asset = session.get(Asset, version.primary_output_asset_id)
    if asset is None:
        return None
    return s3.get_object(asset.object_key)


def _active_link(session: Session, *, user_id: str, channel: str) -> PlatformAccountLink | None:
    return session.scalar(
        select(PlatformAccountLink).where(
            PlatformAccountLink.user_id == user_id,
            PlatformAccountLink.channel == channel,
            PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
        )
    )


def _client_for(channel: str) -> PlatformClient:
    client = _CLIENTS.get(channel)
    if client is None:
        raise ValidationFailed(f"不支持的分发渠道: {channel}")
    return client


def _sign_state(*, user_id: str, channel: str) -> str:
    """HMAC-signs `{user_id, channel, ts}` with `settings.jwt_secret`.

    Reuses the JWT secret rather than inventing a new one: it is already an
    env-sourced value with the right entropy for HMAC-SHA256, and rotating it
    already has an established operational story.
    """
    payload = {"user_id": user_id, "channel": channel, "ts": int(time.time())}
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_hmac(payload_b64)}"


def _verify_state(state: str, *, expected_channel: str) -> str:
    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError as exc:
        raise PlatformOAuthFailed("授权状态无效。") from exc

    if not hmac.compare_digest(signature, _hmac(payload_b64)):
        raise PlatformOAuthFailed("授权状态签名校验失败。")

    try:
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlatformOAuthFailed("授权状态无效。") from exc

    if not isinstance(payload, dict) or payload.get("channel") != expected_channel:
        raise PlatformOAuthFailed("授权状态渠道不匹配。")

    issued_at = payload.get("ts")
    # A small negative allowance absorbs clock skew between processes; a
    # state minted more than `STATE_TTL_SECONDS` in the past is stale.
    if not isinstance(issued_at, int) or not (-60 <= time.time() - issued_at <= STATE_TTL_SECONDS):
        raise PlatformOAuthFailed("授权状态已过期，请重新发起连接。")

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise PlatformOAuthFailed("授权状态无效。")
    return user_id


def _hmac(payload_b64: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
