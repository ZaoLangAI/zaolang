"""User-published learning posts.

Submitting or editing a post always lands in `PENDING`: content that changed
must be re-reviewed, so `update` deliberately never preserves a prior
approval. Visibility follows the same "hide existence" rule as private works
— an unapproved post looks identical to a missing one to anyone but its
author, via `NotFound` rather than `Forbidden`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import Asset, LearnPost
from app.models.base import utcnow
from app.models.enums import AssetRole, LearnPostLevel, LearnPostStatus

MAX_BODY_MARKDOWN_LENGTH = 20_000
MAX_BODY_IMAGES = 20

# 正文里插入图片只能通过应用内上传得到的 asset id 引用，不接受任意外链
# ——否则一条内容通过审核后，作者可以悄悄把外链图片换成别的内容，审核形同虚设。
ASSET_URL_SCHEME = "learn-asset:"
_IMAGE_DESTINATION_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)")


@dataclass(slots=True)
class ListPage:
    items: list[LearnPost]
    next_cursor: str | None
    has_more: bool


def submit(
    session: Session,
    *,
    author_user_id: str,
    title: str,
    summary: str,
    level: LearnPostLevel,
    cover_asset_id: str | None,
    body_markdown: str,
) -> LearnPost:
    _assert_media_owned(session, author_user_id=author_user_id, cover_asset_id=cover_asset_id)
    _assert_body_markdown_valid(session, author_user_id=author_user_id, body_markdown=body_markdown)

    post = LearnPost(
        author_user_id=author_user_id,
        title=title,
        summary=summary,
        level=level,
        cover_asset_id=cover_asset_id,
        body_markdown=body_markdown,
        status=LearnPostStatus.PENDING,
    )
    session.add(post)
    session.flush()
    return post


def update(
    session: Session,
    *,
    post: LearnPost,
    actor_user_id: str,
    title: str,
    summary: str,
    level: LearnPostLevel,
    cover_asset_id: str | None,
    body_markdown: str,
) -> LearnPost:
    if post.author_user_id != actor_user_id:
        raise Forbidden("只能编辑自己发表的内容。")

    _assert_media_owned(session, author_user_id=actor_user_id, cover_asset_id=cover_asset_id)
    _assert_body_markdown_valid(session, author_user_id=actor_user_id, body_markdown=body_markdown)

    post.title = title
    post.summary = summary
    post.level = level
    post.cover_asset_id = cover_asset_id
    post.body_markdown = body_markdown

    # 内容安全底线：改过内容必须重新过审，不因为“只是小改动”而绕过。
    post.status = LearnPostStatus.PENDING
    post.reviewed_by_user_id = None
    post.reviewed_at = None
    post.reject_reason = None
    post.published_at = None

    session.flush()
    return post


def withdraw(session: Session, *, post: LearnPost, actor_user_id: str) -> LearnPost:
    if post.author_user_id != actor_user_id:
        raise Forbidden("只能撤回自己发表的内容。")
    if post.status == LearnPostStatus.WITHDRAWN:
        return post

    post.status = LearnPostStatus.WITHDRAWN
    post.published_at = None
    session.flush()
    return post


def get_visible(session: Session, *, post_id: str, viewer_id: str | None) -> LearnPost:
    post = session.get(LearnPost, post_id)
    if post is None:
        raise NotFound("内容不存在。")
    if post.status == LearnPostStatus.APPROVED:
        return post
    if viewer_id is not None and post.author_user_id == viewer_id:
        return post
    # 未通过审核的内容对外表现为“不存在”，不暴露“存在但你无权看”。
    raise NotFound("内容不存在。")


def list_public(
    session: Session,
    *,
    level: LearnPostLevel | None = None,
    cursor: str | None = None,
    limit: int = 24,
) -> ListPage:
    anchor: LearnPost | None = None
    if cursor:
        anchor = session.get(LearnPost, cursor)
        if anchor is None or anchor.status != LearnPostStatus.APPROVED:
            # 未知或已不再可见的游标：视为翻页已到底，避免无限滚动死循环。
            return ListPage(items=[], next_cursor=None, has_more=False)

    stmt = select(LearnPost).where(LearnPost.status == LearnPostStatus.APPROVED)
    if level:
        stmt = stmt.where(LearnPost.level == level)
    stmt = stmt.order_by(LearnPost.published_at.desc(), LearnPost.id.desc())
    if anchor is not None:
        stmt = stmt.where(_after_published(anchor))

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]
    return ListPage(
        items=items, next_cursor=items[-1].id if has_more and items else None, has_more=has_more
    )


def list_mine(session: Session, *, author_user_id: str, limit: int = 24) -> ListPage:
    """作者本人的全部状态，一次取满即可——单个用户的发表量通常不大。"""
    stmt = (
        select(LearnPost)
        .where(LearnPost.author_user_id == author_user_id)
        .order_by(LearnPost.created_at.desc(), LearnPost.id.desc())
        .limit(limit + 1)
    )
    rows = list(session.scalars(stmt))
    has_more = len(rows) > limit
    return ListPage(items=rows[:limit], next_cursor=None, has_more=has_more)


def admin_list(
    session: Session, *, status: LearnPostStatus | None = None, limit: int = 50
) -> list[LearnPost]:
    stmt = (
        select(LearnPost)
        .where(LearnPost.status == (status or LearnPostStatus.PENDING))
        .order_by(LearnPost.created_at)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def approve(session: Session, *, post: LearnPost, reviewer_user_id: str) -> LearnPost:
    if post.status != LearnPostStatus.PENDING:
        raise Conflict("只能对待审核内容做出审核决定。")

    now = utcnow()
    post.status = LearnPostStatus.APPROVED
    post.reviewed_by_user_id = reviewer_user_id
    post.reviewed_at = now
    post.published_at = now
    post.reject_reason = None
    session.flush()
    return post


def reject(session: Session, *, post: LearnPost, reviewer_user_id: str, reason: str) -> LearnPost:
    if post.status != LearnPostStatus.PENDING:
        raise Conflict("只能对待审核内容做出审核决定。")
    if not reason.strip():
        raise ValidationFailed("拒绝必须填写理由。")

    post.status = LearnPostStatus.REJECTED
    post.reviewed_by_user_id = reviewer_user_id
    post.reviewed_at = utcnow()
    post.reject_reason = reason
    post.published_at = None
    session.flush()
    return post


def _after_published(anchor: LearnPost) -> ColumnElement[bool]:
    """`ORDER BY published_at DESC, id DESC` 的翻页边界。

    只有 APPROVED 记录才会作为游标锚点（见 `list_public` 的校验），而
    APPROVED 必然已在 `approve()` 里写入 `published_at`，因此这里不需要像
    `search.service._after_published` 那样处理 null。
    """
    published_at = anchor.published_at
    assert published_at is not None
    return or_(
        LearnPost.published_at < published_at,
        and_(LearnPost.published_at == published_at, LearnPost.id < anchor.id),
    )


def _assert_media_owned(
    session: Session, *, author_user_id: str, cover_asset_id: str | None
) -> None:
    if cover_asset_id:
        _assert_asset_owned(session, author_user_id=author_user_id, asset_id=cover_asset_id)


def iter_body_asset_ids(body_markdown: str) -> list[str]:
    """按出现顺序取出正文里引用的素材 id，去重但保留首次出现的顺序。

    供 API 层复用：把 markdown 存的是 `learn-asset:{id}` 这个不会过期的引用，
    每次读取时都要重新解析出这份 id 列表，换成当下有效的签名 URL。
    """
    seen: dict[str, None] = {}
    for destination in _IMAGE_DESTINATION_PATTERN.findall(body_markdown):
        if destination.startswith(ASSET_URL_SCHEME):
            seen.setdefault(destination.removeprefix(ASSET_URL_SCHEME), None)
    return list(seen)


def _assert_body_markdown_valid(
    session: Session, *, author_user_id: str, body_markdown: str
) -> None:
    if len(body_markdown) > MAX_BODY_MARKDOWN_LENGTH:
        raise ValidationFailed(
            f"正文不能超过 {MAX_BODY_MARKDOWN_LENGTH} 字。", limit=MAX_BODY_MARKDOWN_LENGTH
        )

    destinations = _IMAGE_DESTINATION_PATTERN.findall(body_markdown)
    if len(destinations) > MAX_BODY_IMAGES:
        raise ValidationFailed(
            f"正文图片数量不能超过 {MAX_BODY_IMAGES} 张。", limit=MAX_BODY_IMAGES
        )

    for destination in destinations:
        if not destination.startswith(ASSET_URL_SCHEME):
            raise ValidationFailed("正文图片只能通过应用内上传插入，不支持外部图片链接。")
        asset_id = destination.removeprefix(ASSET_URL_SCHEME)
        _assert_asset_owned(session, author_user_id=author_user_id, asset_id=asset_id)


def _assert_asset_owned(session: Session, *, author_user_id: str, asset_id: str) -> None:
    asset = session.get(Asset, asset_id)
    if (
        asset is None
        or asset.owner_user_id != author_user_id
        or asset.role != AssetRole.LEARN_MEDIA
    ):
        raise ValidationFailed("素材不存在或不属于当前用户。", asset_id=asset_id)
