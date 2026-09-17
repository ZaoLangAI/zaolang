"""`learning.catalog` and `learning_service.ensure_catalog_posts`: the
platform-curated `LearnPost` tutorial catalogue `make seed` plants."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.learning import catalog as learning_catalog
from app.domain.learning import service as learning_service
from app.models import Asset, LearnPost, User
from app.models.base import new_id, utcnow
from app.models.enums import AssetRole, LearnPostStatus, MediaType


def test_ensure_catalog_posts_plants_the_whole_catalogue(db: Session, author: User) -> None:
    created = learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    assert len(created) == len(learning_catalog.CATALOG)
    rows = db.scalars(select(LearnPost).where(LearnPost.author_user_id == author.id)).all()
    assert len(rows) == len(learning_catalog.CATALOG)
    for row in rows:
        assert row.status == LearnPostStatus.APPROVED
        assert row.published_at is not None
        assert row.reviewed_by_user_id is None
        assert row.reviewed_at is None


def test_ensure_catalog_posts_is_idempotent(db: Session, author: User) -> None:
    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    second_run = learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    assert second_run == []
    rows = db.scalars(select(LearnPost).where(LearnPost.author_user_id == author.id)).all()
    assert len(rows) == len(learning_catalog.CATALOG)


def test_ensure_catalog_posts_does_not_overwrite_an_operator_edit(
    db: Session, author: User
) -> None:
    """A title already present for this author is left alone — an operator's
    hand-edit to a previously-seeded row must survive a later `make seed`."""
    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    sample = learning_catalog.CATALOG[0]
    row = db.scalar(
        select(LearnPost).where(
            LearnPost.author_user_id == author.id, LearnPost.title == sample.title
        )
    )
    assert row is not None
    row.summary = "运营改过的简介"
    db.commit()

    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    db.expire_all()
    row = db.scalar(
        select(LearnPost).where(
            LearnPost.author_user_id == author.id, LearnPost.title == sample.title
        )
    )
    assert row is not None
    assert row.summary == "运营改过的简介"


def test_ensure_catalog_posts_backfills_a_cover_for_every_entry(db: Session, author: User) -> None:
    """Every catalogue entry ships a `seed_covers/<key>.jpg` — see
    `LearnPostSeed.cover_path`. `ensure_catalog_posts` must attach one to
    every seeded row's `cover_asset_id`, not leave the learn grid empty."""
    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    rows = db.scalars(select(LearnPost).where(LearnPost.author_user_id == author.id)).all()
    assert len(rows) == len(learning_catalog.CATALOG)
    for row in rows:
        item = next(entry for entry in learning_catalog.CATALOG if entry.title == row.title)
        assert item.cover_path() is not None, f"{item.key} shipped with no cover"
        assert row.cover_asset_id is not None, f"{row.title} has no cover_asset_id"
        asset = db.get(Asset, row.cover_asset_id)
        assert asset is not None
        assert asset.role == AssetRole.LEARN_MEDIA
        assert asset.owner_user_id == author.id


def test_ensure_catalog_posts_backfills_cover_on_an_existing_coverless_row(
    db: Session, author: User
) -> None:
    """A previously-seeded row that still has no cover (the pre-cover
    catalogue) must receive one on a later `make seed` / `ensure_catalog`,
    without rewriting title/summary/body."""
    sample = learning_catalog.CATALOG[0]
    post = LearnPost(
        author_user_id=author.id,
        title=sample.title,
        summary="运营改过的简介",
        level=sample.level,
        cover_asset_id=None,
        body_markdown=sample.body_markdown,
        status=LearnPostStatus.APPROVED,
        published_at=utcnow(),
    )
    db.add(post)
    db.commit()

    created = learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    assert sample.title not in {row.title for row in created}
    db.refresh(post)
    assert post.summary == "运营改过的简介"
    assert post.cover_asset_id is not None
    asset = db.get(Asset, post.cover_asset_id)
    assert asset is not None
    assert asset.role == AssetRole.LEARN_MEDIA


def test_ensure_catalog_posts_does_not_overwrite_an_operators_cover(
    db: Session, author: User
) -> None:
    """A cover already set — from an earlier backfill or an operator's own
    re-cover — is never replaced by a later `make seed`."""
    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    sample_title = learning_catalog.CATALOG[0].title
    row = db.scalar(
        select(LearnPost).where(
            LearnPost.author_user_id == author.id, LearnPost.title == sample_title
        )
    )
    assert row is not None
    original_cover_asset_id = row.cover_asset_id
    assert original_cover_asset_id is not None
    replacement = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1,
        checksum_sha256="0" * 64,
        role=AssetRole.LEARN_MEDIA,
    )
    db.add(replacement)
    db.flush()
    row.cover_asset_id = replacement.id
    db.commit()

    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    db.expire_all()
    row = db.scalar(
        select(LearnPost).where(
            LearnPost.author_user_id == author.id, LearnPost.title == sample_title
        )
    )
    assert row is not None
    assert row.cover_asset_id == replacement.id


def test_a_seeded_post_is_visible_without_login(db: Session, author: User) -> None:
    learning_service.ensure_catalog_posts(db, author_user_id=author.id)
    db.commit()

    sample = learning_catalog.find("prompt-101-first-clip")
    assert sample is not None
    row = db.scalar(
        select(LearnPost).where(
            LearnPost.author_user_id == author.id, LearnPost.title == sample.title
        )
    )
    assert row is not None

    visible = learning_service.get_visible(db, post_id=row.id, viewer_id=None)
    assert visible.id == row.id
    assert visible.body_markdown == sample.body_markdown

    page = learning_service.list_public(db, level=sample.level)
    assert any(item.id == row.id for item in page.items)
