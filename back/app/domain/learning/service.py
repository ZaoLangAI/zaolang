"""User-published learning posts.

Submitting or editing a post always lands in `PENDING`: content that changed
must be re-reviewed, so `update` deliberately never preserves a prior
approval. Visibility follows the same "hide existence" rule as private works
— an unapproved post looks identical to a missing one to anyone but its
author, via `NotFound` rather than `Forbidden`.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

from PIL import Image
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.learning import catalog as learning_catalog
from app.domain.moderation_policy import assert_allowed
from app.models import Asset, LearnPost
from app.models.base import utcnow
from app.models.enums import (
    AssetRole,
    LearnPostLevel,
    LearnPostStatus,
    MediaType,
    ModerationStatus,
    Visibility,
)
from app.storage import s3

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
    assert_allowed(
        session,
        config_key="learning_moderation",
        texts=[title, summary, body_markdown],
        user_id=author_user_id,
        subject_type="learn_post",
    )
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


def ensure_catalog_posts(session: Session, *, author_user_id: str) -> list[LearnPost]:
    """Plants `catalog.CATALOG`'s platform-curated "学习" tutorials.

    A system-default catalogue, analogous to
    `skill_library_service.ensure_catalog_skills` — not a real user
    submission — so it skips `submit()`'s pending-review flow entirely and
    writes straight to `APPROVED`/`published_at=now`. It never runs
    `assert_allowed`/opens a moderation queue item and leaves
    `reviewed_by_user_id`/`reviewed_at` as `None` by design: there is no
    human review to record for a row nothing ever submitted for review.

    Idempotent and additive, matched by `(author_user_id, title)` since
    `LearnPost` has no dedicated catalogue-key column: a title already
    present for this author is left untouched, so an operator's own edit to
    a previously-seeded row survives a later re-run. The one exception is
    `cover_asset_id`: a row (new or pre-existing) that still has none gets
    one backfilled from `catalog.py`'s shipped cover, but a row that already
    carries one — whether from an earlier run of this same backfill or an
    operator's own re-cover — is never touched (see `_ensure_seeded_cover`).
    """
    existing = {
        row.title: row
        for row in session.scalars(
            select(LearnPost).where(LearnPost.author_user_id == author_user_id)
        )
    }
    created: list[LearnPost] = []
    now = utcnow()
    for item in learning_catalog.CATALOG:
        post = existing.get(item.title)
        if post is None:
            post = LearnPost(
                author_user_id=author_user_id,
                title=item.title,
                summary=item.summary,
                level=item.level,
                cover_asset_id=None,
                body_markdown=item.body_markdown,
                status=LearnPostStatus.APPROVED,
                published_at=now,
            )
            session.add(post)
            session.flush()
            created.append(post)
        _ensure_seeded_cover(session, post=post, item=item, author_user_id=author_user_id)
    return created


def _ensure_seeded_cover(
    session: Session,
    *,
    post: LearnPost,
    item: learning_catalog.LearnPostSeed,
    author_user_id: str,
) -> None:
    """Backfills a catalogue post's cover from its shipped `seed_covers/`
    JPEG, the same "system-default, not a stand-in for real content" content
    class as the post rows themselves (see `ensure_catalog_posts`'s
    docstring).

    A no-op once `cover_asset_id` is set, from any source — this never
    replaces a cover, so an operator swapping one out survives every later
    `make seed`. Role is `LEARN_MEDIA` (not `COVER`) so a later C-end edit
    that keeps this cover still passes `_assert_asset_owned`.
    """
    if post.cover_asset_id is not None:
        return
    cover_path = item.cover_path()
    if cover_path is None:
        return

    payload = cover_path.read_bytes()
    with Image.open(io.BytesIO(payload)) as image:
        width, height = image.size

    object_key = f"seed/learning/{item.key}.jpg"
    s3.put_object(object_key, payload, content_type="image/jpeg")

    asset = Asset(
        owner_user_id=author_user_id,
        object_key=object_key,
        media_type=MediaType.IMAGE,
        mime_type="image/jpeg",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=AssetRole.LEARN_MEDIA,
        width=width,
        height=height,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        is_prototype=False,
    )
    session.add(asset)
    session.flush()
    post.cover_asset_id = asset.id
    session.flush()


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

    assert_allowed(
        session,
        config_key="learning_moderation",
        texts=[title, summary, body_markdown],
        user_id=actor_user_id,
        subject_type="learn_post",
    )

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
