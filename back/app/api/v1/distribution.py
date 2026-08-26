"""Platform-account connect/callback/list/disconnect and fan-out publish.

Routes only parse/validate and call `app.domain.distribution.service` —
no platform-specific logic lives here. See that module's docstring for the
security posture (state signing, token encryption, per-channel failure
isolation).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.distribution import (
    AuthorizeUrlResponse,
    ConfigStatusResponse,
    EpisodeExternalMetricResponse,
    PlatformAccountLinkResponse,
    PublicationFanoutItem,
    PublicationFanoutRequest,
    PublicationFanoutResponse,
)
from app.domain.distribution import service as distribution

router = APIRouter(tags=["distribution"])

PUBLICATIONS_FANOUT_ENDPOINT = "POST /v1/works/{work_id}/publications:fanout"


@router.get("/platform-accounts/config-status", response_model=ConfigStatusResponse)
def config_status(
    _user: CurrentUser,
    __: Annotated[None, Depends(rate_limited("public_read"))],
) -> ConfigStatusResponse:
    status = distribution.config_status()
    return ConfigStatusResponse(**status)


@router.get("/platform-accounts/{channel}/connect", response_model=AuthorizeUrlResponse)
def connect(
    channel: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> AuthorizeUrlResponse:
    url = distribution.connect_start(session, user_id=user.id, channel=channel)
    return AuthorizeUrlResponse(authorize_url=url)


@router.get("/platform-accounts/{channel}/callback", response_model=PlatformAccountLinkResponse)
def callback(
    channel: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> PlatformAccountLinkResponse:
    link = distribution.connect_callback(session, channel=channel, code=code, state=state)
    session.commit()
    return _link_response(link)


@router.get("/platform-accounts", response_model=list[PlatformAccountLinkResponse])
def list_accounts(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[PlatformAccountLinkResponse]:
    return [_link_response(item) for item in distribution.list_linked_accounts(session, user_id=user.id)]


@router.delete("/platform-accounts/{link_id}", response_model=PlatformAccountLinkResponse)
def disconnect(
    link_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> PlatformAccountLinkResponse:
    link = distribution.disconnect(session, user_id=user.id, link_id=link_id)
    session.commit()
    return _link_response(link)


@router.post(
    "/works/{work_id}/publications:fanout",
    response_model=PublicationFanoutResponse,
    status_code=201,
)
def publish_fanout(
    work_id: str,
    payload: PublicationFanoutRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("platform_publish"))],
) -> PublicationFanoutResponse:
    """One-click publish to every requested channel.

    A channel that isn't configured/linked, or that fails, never blocks the
    others — see `distribution.publish_fanout`'s own docstring.
    """
    request_hash = idempotency.hash_request(
        {"work_id": work_id, **payload.model_dump(mode="json")}
    )
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=PUBLICATIONS_FANOUT_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return PublicationFanoutResponse.model_validate(replay.response_snapshot)

    results = distribution.publish_fanout(
        session,
        user_id=user.id,
        work_id=work_id,
        channels=[str(channel) for channel in payload.channels],
        title=payload.title,
        description=payload.description,
        hashtags=payload.hashtags,
    )
    response = PublicationFanoutResponse(
        work_id=work_id,
        results=[
            PublicationFanoutItem(
                channel=item.channel,
                status=item.status,
                external_post_id=item.external_post_id,
                error=item.error,
                reason=item.reason,
            )
            for item in results
        ],
    )

    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=PUBLICATIONS_FANOUT_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=201,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    return response


@router.get("/works/{work_id}/metrics", response_model=list[EpisodeExternalMetricResponse])
def list_metrics(
    work_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[EpisodeExternalMetricResponse]:
    return [
        EpisodeExternalMetricResponse(
            channel=item.channel,
            external_post_id=item.external_post_id,
            view_count=item.view_count,
            like_count=item.like_count,
            comment_count=item.comment_count,
            share_count=item.share_count,
            fetched_at=item.fetched_at,
        )
        for item in distribution.list_metrics_for_work(session, user_id=user.id, work_id=work_id)
    ]


def _link_response(link) -> PlatformAccountLinkResponse:  # type: ignore[no-untyped-def]
    return PlatformAccountLinkResponse(
        id=link.id,
        channel=link.channel,
        external_account_id=link.external_account_id,
        external_account_label=link.external_account_label,
        status=link.status,
        connected_at=link.connected_at,
        token_expires_at=link.token_expires_at,
    )
