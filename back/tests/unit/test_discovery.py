"""Discovery: embeddings, hybrid ranking, similarity and tag browsing."""

from __future__ import annotations

import math

import pytest
from sqlalchemy.orm import Session

from app.domain.search import embeddings
from app.domain.search import service as search_service
from app.models import Tag, User, Work, WorkEmbedding, WorkTag, WorkVersion
from app.models.base import utcnow
from app.models.enums import LifecycleStatus, Visibility
from app.models.search import EMBEDDING_DIM

# --- the embedding provider ----------------------------------------------


def test_the_same_text_always_produces_the_same_vector() -> None:
    """CI and local runs must agree, so the default provider cannot be random."""
    assert embeddings.embed("晨雾中的山谷") == embeddings.embed("晨雾中的山谷")


def test_a_vector_has_the_dimension_the_column_expects() -> None:
    """A mismatch would only surface as a database error at insert time."""
    assert len(embeddings.embed("cinematic sunrise")) == EMBEDDING_DIM


def test_a_vector_is_unit_length() -> None:
    """Cosine distance is only meaningful on normalised vectors."""
    vector = embeddings.embed("cinematic sunrise over the sea")
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_empty_text_yields_a_zero_vector_rather_than_an_error() -> None:
    assert not any(embeddings.embed("   "))


def test_different_texts_produce_different_vectors() -> None:
    assert embeddings.embed("红色的猫") != embeddings.embed("蓝色的狗")


def test_word_order_changes_the_vector() -> None:
    """ "red on blue" and "blue on red" are different prompts."""
    assert embeddings.embed("red on blue") != embeddings.embed("blue on red")


def test_the_provider_is_swappable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway has no embedding model today; the interface exists so that
    changing that is a provider swap, not a rewrite."""

    class Fixed(embeddings.EmbeddingProvider):
        name = "fixed"
        dimension = EMBEDDING_DIM

        def embed(self, text: str) -> list[float]:
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    original = embeddings.get_provider()
    try:
        embeddings.set_provider(Fixed())
        assert embeddings.get_provider().name == "fixed"
        assert embeddings.embed("anything")[0] == 1.0
    finally:
        embeddings.set_provider(original)


# --- indexing and search --------------------------------------------------


def _publish_work(
    db: Session,
    owner: User,
    *,
    title: str,
    description: str = "",
    prompt: str = "",
    visibility: str = Visibility.PUBLIC_REMIXABLE,
    lifecycle: str = LifecycleStatus.ACTIVE,
    tags: tuple[str, ...] = (),
) -> tuple[Work, WorkVersion]:
    work = Work(
        owner_user_id=owner.id,
        visibility=visibility,
        lifecycle_status=lifecycle,
        published_at=utcnow(),
    )
    db.add(work)
    db.flush()

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        description=description or None,
        reusable_params_json={"prompt": prompt} if prompt else {},
        immutable_created_at=utcnow(),
    )
    db.add(version)
    db.flush()
    work.current_version_id = version.id

    for slug in tags:
        tag = Tag(slug=slug, label_zh=slug, label_en=slug, label_ja=slug, usage_count=1)
        db.add(tag)
        db.flush()
        db.add(WorkTag(work_id=work.id, tag_id=tag.id))

    search_service.index_version(db, work=work, version=version)
    db.flush()
    return work, version


def test_indexing_stores_a_vector_for_the_version(db: Session, author: User) -> None:
    _, version = _publish_work(db, author, title="海上日出", prompt="sunrise over the sea")
    stored = db.scalar(
        WorkEmbedding.__table__.select().where(WorkEmbedding.work_version_id == version.id)
    )
    assert stored is not None


def test_reindexing_updates_in_place_rather_than_duplicating(db: Session, author: User) -> None:
    work, version = _publish_work(db, author, title="海上日出")
    search_service.index_version(db, work=work, version=version)

    rows = list(
        db.scalars(
            WorkEmbedding.__table__.select()
            .where(WorkEmbedding.work_version_id == version.id)
            .with_only_columns(WorkEmbedding.__table__.c.id)
        )
    )
    assert len(rows) == 1


def test_keyword_search_finds_a_title_match(db: Session, author: User) -> None:
    _publish_work(db, author, title="海上日出")
    _publish_work(db, author, title="森林深处")

    hits = search_service.search(db, query="海上", semantic=False)
    assert [h.version.title for h in hits] == ["海上日出"]


def test_keyword_search_also_matches_the_description(db: Session, author: User) -> None:
    _publish_work(db, author, title="无题", description="一场关于海上日出的实验")
    hits = search_service.search(db, query="日出", semantic=False)
    assert len(hits) == 1


def test_a_title_hit_outranks_a_description_only_hit(db: Session, author: User) -> None:
    """The title is what the user can predict will match."""
    _publish_work(db, author, title="日出", description="")
    _publish_work(db, author, title="无题", description="拍的是日出")

    hits = search_service.search(db, query="日出", semantic=False)
    assert hits[0].version.title == "日出"


def test_search_never_returns_a_private_work(db: Session, author: User) -> None:
    _publish_work(db, author, title="私密日出", visibility=Visibility.PRIVATE)
    assert search_service.search(db, query="日出") == []


def test_search_never_returns_a_tombstoned_work(db: Session, author: User) -> None:
    """A tombstone stays in the chain but must leave discovery."""
    _publish_work(db, author, title="下架日出", lifecycle=LifecycleStatus.TOMBSTONE)
    assert search_service.search(db, query="日出") == []


def test_remixable_only_excludes_view_only_works(db: Session, author: User) -> None:
    _publish_work(db, author, title="可二创日出", visibility=Visibility.PUBLIC_REMIXABLE)
    _publish_work(db, author, title="仅展示日出", visibility=Visibility.PUBLIC_VIEW_ONLY)

    hits = search_service.search(db, query="日出", remixable_only=True, semantic=False)
    assert [h.version.title for h in hits] == ["可二创日出"]


def test_hybrid_search_marks_a_work_matched_both_ways(db: Session, author: User) -> None:
    """Matching on keyword and vector is a stronger signal than either alone."""
    _publish_work(db, author, title="cinematic sunrise", prompt="cinematic sunrise")
    hits = search_service.search(db, query="cinematic sunrise", semantic=True)
    assert hits
    assert hits[0].matched_by == "hybrid"


def test_a_work_matched_both_ways_outranks_one_matched_once(db: Session, author: User) -> None:
    _publish_work(db, author, title="cinematic sunrise", prompt="cinematic sunrise")
    _publish_work(db, author, title="cinematic sunrise study", prompt="完全无关的内容")

    hits = search_service.search(db, query="cinematic sunrise", semantic=True)
    assert hits[0].version.title == "cinematic sunrise"
    assert hits[0].score > hits[1].score


def test_an_empty_query_falls_back_to_browsing(db: Session, author: User) -> None:
    _publish_work(db, author, title="海上日出")
    assert len(search_service.search(db, query="   ")) == 1


def test_a_query_matching_nothing_returns_nothing(db: Session, author: User) -> None:
    _publish_work(db, author, title="海上日出")
    assert search_service.search(db, query="完全不相干的词", semantic=False) == []


def test_search_respects_the_limit(db: Session, author: User) -> None:
    for index in range(5):
        _publish_work(db, author, title=f"日出 {index}")
    assert len(search_service.search(db, query="日出", semantic=False, limit=2)) == 2


# --- similarity and browsing ---------------------------------------------


def test_similar_works_exclude_the_source_itself(db: Session, author: User) -> None:
    _, version = _publish_work(db, author, title="海上日出", prompt="sunrise sea")
    _publish_work(db, author, title="海上日落", prompt="sunset sea")

    similar = search_service.similar_works(db, work_version_id=version.id)
    assert version.id not in [s.version.id for s in similar]


def test_similar_works_rank_the_closest_first(db: Session, author: User) -> None:
    _, source = _publish_work(db, author, title="海上日出", prompt="cinematic sunrise over the sea")
    _publish_work(db, author, title="海上日落", prompt="cinematic sunset over the sea")
    _publish_work(db, author, title="城市街道", prompt="neon city street at night")

    similar = search_service.similar_works(db, work_version_id=source.id)
    assert similar[0].version.title == "海上日落"


def test_similarity_of_an_unindexed_version_is_empty_not_an_error(
    db: Session, author: User
) -> None:
    assert search_service.similar_works(db, work_version_id="wv_missing") == []


def test_browsing_by_tag_filters_to_that_tag(db: Session, author: User) -> None:
    _publish_work(db, author, title="海上日出", tags=("sunrise",))
    _publish_work(db, author, title="森林深处", tags=("forest",))

    hits = search_service.browse(db, tag="sunrise")
    assert [h.version.title for h in hits] == ["海上日出"]


def test_browsing_by_popularity_puts_the_most_liked_first(db: Session, author: User) -> None:
    quiet, _ = _publish_work(db, author, title="冷门")
    loved, _ = _publish_work(db, author, title="热门")
    loved.like_count = 42
    quiet.like_count = 1
    db.flush()

    hits = search_service.browse(db, sort="popular")
    assert hits[0].version.title == "热门"


def test_browsing_by_remix_count_puts_the_most_remixed_first(db: Session, author: User) -> None:
    _publish_work(db, author, title="没人续作")
    forked, _ = _publish_work(db, author, title="很多人续作")
    forked.remix_count = 9
    db.flush()

    hits = search_service.browse(db, sort="remixed")
    assert hits[0].version.title == "很多人续作"


def test_browsing_excludes_private_and_tombstoned_works(db: Session, author: User) -> None:
    _publish_work(db, author, title="公开")
    _publish_work(db, author, title="私密", visibility=Visibility.PRIVATE)
    _publish_work(db, author, title="下架", lifecycle=LifecycleStatus.TOMBSTONE)

    titles = {h.version.title for h in search_service.browse(db)}
    assert titles == {"公开"}
