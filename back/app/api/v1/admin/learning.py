"""Back-office review queue for user-published learning posts."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession
from app.api.schemas.admin import LearnPostAdminView, LearnPostDecisionRequest
from app.api.schemas.common import Page
from app.api.v1.admin.deps import AdminRead, AdminWrite, Reviewer, Viewer
from app.domain.audit import service as audit
from app.domain.errors import NotFound, ReasonRequired
from app.domain.learning import service as learning
from app.domain.notifications import push as notifications
from app.models import LearnPost
from app.models.enums import LearnPostStatus, NotificationType
from app.presenters import media_urls
from app.presenters.learn_body import resolve_body_asset_urls

router = APIRouter(tags=["admin:learning"])


@router.get("/learn-posts", response_model=Page[LearnPostAdminView])
def list_learn_posts(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: LearnPostStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[LearnPostAdminView]:
    posts = learning.admin_list(session, status=status, limit=limit)
    return Page(items=[_view(session, post) for post in posts])


@router.post("/learn-posts/{post_id}/approve", response_model=LearnPostAdminView)
def approve(
    post_id: str, request: Request, session: DbSession, user: Reviewer, _: AdminWrite
) -> LearnPostAdminView:
    post = _require_post(session, post_id)
    before = {"status": post.status}

    learning.approve(session, post=post, reviewer_user_id=user.id)
    notifications.notify(
        session,
        user_id=post.author_user_id,
        type=NotificationType.MODERATION,
        title_key="notification.learn_post_approved",
        payload={"title": post.title},
        target_type="learn_post",
        target_id=post.id,
    )

    audit.record(
        session,
        actor=user,
        action="learn_post.approve",
        target_type="learn_post",
        target_id=post.id,
        before=before,
        after={"status": post.status},
        request=request,
    )
    session.commit()
    return _view(session, post)


@router.post("/learn-posts/{post_id}/reject", response_model=LearnPostAdminView)
def reject(
    post_id: str,
    payload: LearnPostDecisionRequest,
    request: Request,
    session: DbSession,
    user: Reviewer,
    _: AdminWrite,
) -> LearnPostAdminView:
    if not (payload.reason or "").strip():
        raise ReasonRequired()

    post = _require_post(session, post_id)
    before = {"status": post.status}

    learning.reject(session, post=post, reviewer_user_id=user.id, reason=payload.reason or "")
    notifications.notify(
        session,
        user_id=post.author_user_id,
        type=NotificationType.MODERATION,
        title_key="notification.learn_post_rejected",
        payload={"title": post.title, "reason": payload.reason or ""},
        target_type="learn_post",
        target_id=post.id,
    )

    audit.record(
        session,
        actor=user,
        action="learn_post.reject",
        target_type="learn_post",
        target_id=post.id,
        before=before,
        after={"status": post.status},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(session, post)


def _require_post(session: DbSession, post_id: str) -> LearnPost:
    post = session.get(LearnPost, post_id)
    if post is None:
        raise NotFound("内容不存在。")
    return post


def _view(session: DbSession, post: LearnPost) -> LearnPostAdminView:
    return LearnPostAdminView(
        id=post.id,
        author_user_id=post.author_user_id,
        title=post.title,
        summary=post.summary,
        level=post.level,
        status=LearnPostStatus(post.status),
        cover_url=media_urls.asset_url(session, post.cover_asset_id),
        body_markdown=post.body_markdown,
        asset_urls=resolve_body_asset_urls(session, post.body_markdown),
        reject_reason=post.reject_reason,
        created_at=post.created_at,
    )
