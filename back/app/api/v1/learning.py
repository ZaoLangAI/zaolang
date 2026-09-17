"""User-published learning posts: submit, edit, withdraw, browse."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, OptionalUser, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.learning import (
    LearnPostCreateRequest,
    LearnPostDetail,
    LearnPostSummary,
    LearnPostUpdateRequest,
)
from app.api.schemas.works import AuthorSummary
from app.domain.errors import NotFound
from app.domain.learning import service as learning
from app.models import LearnPost, Profile
from app.models.enums import LearnPostLevel, LearnPostStatus
from app.presenters import media_urls
from app.presenters.learn_body import resolve_body_asset_urls

router = APIRouter(tags=["learning"])

CREATE_ENDPOINT = "POST /v1/learn/posts"


@router.get("/learn/posts", response_model=Page[LearnPostSummary])
def list_posts(
    session: DbSession,
    _viewer: OptionalUser,
    __: Annotated[None, Depends(rate_limited("public_read"))],
    level: LearnPostLevel | None = None,
    cursor: str | None = None,
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[LearnPostSummary]:
    page = learning.list_public(session, level=level, cursor=cursor, limit=limit)
    return Page(
        items=[_summary(session, post) for post in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/learn/posts/mine", response_model=Page[LearnPostSummary])
def list_mine(
    session: DbSession,
    user: CurrentUser,
    _: Annotated[None, Depends(rate_limited("public_read"))],
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[LearnPostSummary]:
    page = learning.list_mine(session, author_user_id=user.id, limit=limit)
    return Page(
        items=[_summary(session, post) for post in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/learn/posts/{post_id}", response_model=LearnPostDetail)
def get_post(post_id: str, session: DbSession, viewer: OptionalUser) -> LearnPostDetail:
    post = learning.get_visible(session, post_id=post_id, viewer_id=viewer.id if viewer else None)
    return _detail(session, post)


@router.post("/learn/posts", response_model=LearnPostDetail, status_code=201)
def create_post(
    payload: LearnPostCreateRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> LearnPostDetail:
    request_hash = idempotency.hash_request(payload.model_dump(mode="json"))
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=CREATE_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return LearnPostDetail.model_validate(replay.response_snapshot)

    post = learning.submit(
        session,
        author_user_id=user.id,
        title=payload.title,
        summary=payload.summary,
        level=payload.level,
        cover_asset_id=payload.cover_asset_id,
        body_markdown=payload.body_markdown,
    )
    response = _detail(session, post)

    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=CREATE_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=201,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    return response


@router.patch("/learn/posts/{post_id}", response_model=LearnPostDetail)
def update_post(
    post_id: str,
    payload: LearnPostUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> LearnPostDetail:
    post = _require_post(session, post_id)
    post = learning.update(
        session,
        post=post,
        actor_user_id=user.id,
        title=payload.title,
        summary=payload.summary,
        level=payload.level,
        cover_asset_id=payload.cover_asset_id,
        body_markdown=payload.body_markdown,
    )
    session.commit()
    return _detail(session, post)


@router.post("/learn/posts/{post_id}/withdraw", response_model=LearnPostDetail)
def withdraw_post(
    post_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> LearnPostDetail:
    post = _require_post(session, post_id)
    post = learning.withdraw(session, post=post, actor_user_id=user.id)
    session.commit()
    return _detail(session, post)


def _require_post(session: DbSession, post_id: str) -> LearnPost:
    post = session.get(LearnPost, post_id)
    if post is None:
        raise NotFound("内容不存在。")
    return post


def _summary(session: DbSession, post: LearnPost) -> LearnPostSummary:
    return LearnPostSummary(
        id=post.id,
        title=post.title,
        summary=post.summary,
        level=LearnPostLevel(post.level),
        cover_url=media_urls.asset_url(session, post.cover_asset_id),
        author=_author(session, post.author_user_id),
        status=LearnPostStatus(post.status),
        published_at=post.published_at,
    )


def _detail(session: DbSession, post: LearnPost) -> LearnPostDetail:
    summary = _summary(session, post)
    return LearnPostDetail(
        **summary.model_dump(),
        cover_asset_id=post.cover_asset_id,
        body_markdown=post.body_markdown,
        asset_urls=resolve_body_asset_urls(session, post.body_markdown),
        reject_reason=post.reject_reason,
        created_at=post.created_at,
    )


def _author(session: DbSession, user_id: str) -> AuthorSummary:
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        return AuthorSummary(user_id=user_id, display_name="未知作者", handle=user_id)
    return AuthorSummary(
        user_id=user_id,
        display_name=profile.display_name,
        handle=profile.handle,
        avatar_url=media_urls.asset_url(session, profile.avatar_asset_id),
    )
