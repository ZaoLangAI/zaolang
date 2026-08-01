"""Discovery: keyword, semantic and hybrid search.

Keyword search alone misses paraphrases; vector search alone drifts off-topic
on short queries. The default blends both, with keyword matches weighted higher
because they are the ones a user can predict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.domain.search import embeddings
from app.models import Tag, Work, WorkEmbedding, WorkTag, WorkVersion
from app.models.enums import LifecycleStatus, Visibility

SortMode = Literal["recent", "popular", "remixed"]

KEYWORD_WEIGHT = 0.6
VECTOR_WEIGHT = 0.4
CANDIDATE_MULTIPLIER = 4


@dataclass(slots=True)
class SearchResult:
    work: Work
    version: WorkVersion
    score: float
    matched_by: str


def _visible_works() -> Select[tuple[Work, WorkVersion]]:
    """Base query: only active, publicly listed works are discoverable."""
    return (
        select(Work, WorkVersion)
        .join(WorkVersion, WorkVersion.id == Work.current_version_id)
        .where(
            Work.lifecycle_status == LifecycleStatus.ACTIVE,
            Work.visibility.in_(
                [Visibility.PUBLIC_REMIXABLE.value, Visibility.PUBLIC_VIEW_ONLY.value]
            ),
        )
    )


def browse(
    session: Session,
    *,
    tag: str | None = None,
    remixable_only: bool = False,
    sort: SortMode = "recent",
    cursor: str | None = None,
    limit: int = 24,
) -> list[SearchResult]:
    stmt = _visible_works()
    if remixable_only:
        stmt = stmt.where(Work.visibility == Visibility.PUBLIC_REMIXABLE)
    if tag:
        stmt = stmt.join(WorkTag, WorkTag.work_id == Work.id).join(
            Tag, (Tag.id == WorkTag.tag_id) & (Tag.slug == tag)
        )

    if sort == "popular":
        stmt = stmt.order_by(Work.like_count.desc(), Work.id.desc())
    elif sort == "remixed":
        stmt = stmt.order_by(Work.remix_count.desc(), Work.id.desc())
    else:
        stmt = stmt.order_by(Work.published_at.desc().nullslast(), Work.id.desc())
        if cursor:
            stmt = stmt.where(Work.id < cursor)

    rows = session.execute(stmt.limit(limit)).all()
    return [
        SearchResult(work=work, version=version, score=0.0, matched_by="browse")
        for work, version in rows
    ]


def search(
    session: Session,
    *,
    query: str,
    semantic: bool = True,
    remixable_only: bool = False,
    limit: int = 24,
) -> list[SearchResult]:
    text = query.strip()
    if not text:
        return browse(session, remixable_only=remixable_only, limit=limit)

    keyword_hits = _keyword_search(session, text, remixable_only, limit * CANDIDATE_MULTIPLIER)
    if not semantic:
        return keyword_hits[:limit]

    vector_hits = _vector_search(session, text, remixable_only, limit * CANDIDATE_MULTIPLIER)

    merged: dict[str, SearchResult] = {}
    for hit in keyword_hits:
        merged[hit.work.id] = SearchResult(
            work=hit.work,
            version=hit.version,
            score=hit.score * KEYWORD_WEIGHT,
            matched_by="keyword",
        )
    for hit in vector_hits:
        existing = merged.get(hit.work.id)
        weighted = hit.score * VECTOR_WEIGHT
        if existing is None:
            merged[hit.work.id] = SearchResult(
                work=hit.work, version=hit.version, score=weighted, matched_by="semantic"
            )
        else:
            # Matching both ways is a strong signal, so the scores add.
            existing.score += weighted
            existing.matched_by = "hybrid"

    ranked = sorted(merged.values(), key=lambda r: (-r.score, r.work.id))
    return ranked[:limit]


def _keyword_search(
    session: Session, text: str, remixable_only: bool, limit: int
) -> list[SearchResult]:
    pattern = f"%{text.lower()}%"
    stmt = _visible_works().where(
        or_(
            func.lower(WorkVersion.title).like(pattern),
            func.lower(func.coalesce(WorkVersion.description, "")).like(pattern),
        )
    )
    if remixable_only:
        stmt = stmt.where(Work.visibility == Visibility.PUBLIC_REMIXABLE)

    rows = session.execute(stmt.limit(limit)).all()
    results = []
    for work, version in rows:
        # A title hit is what the user expects to rank first.
        score = 1.0 if text.lower() in version.title.lower() else 0.6
        results.append(SearchResult(work=work, version=version, score=score, matched_by="keyword"))
    results.sort(key=lambda r: -r.score)
    return results


def _vector_search(
    session: Session, text: str, remixable_only: bool, limit: int
) -> list[SearchResult]:
    vector = embeddings.embed(text)
    if not any(vector):
        return []

    distance = WorkEmbedding.embedding.cosine_distance(vector)
    stmt = (
        _visible_works()
        .join(WorkEmbedding, WorkEmbedding.work_version_id == WorkVersion.id)
        .add_columns(distance.label("distance"))
        .order_by(distance)
        .limit(limit)
    )
    if remixable_only:
        stmt = stmt.where(Work.visibility == Visibility.PUBLIC_REMIXABLE)

    results = []
    for work, version, dist in session.execute(stmt).all():
        results.append(
            SearchResult(
                work=work,
                version=version,
                score=max(0.0, 1.0 - float(dist)),
                matched_by="semantic",
            )
        )
    return results


def similar_works(session: Session, *, work_version_id: str, limit: int = 8) -> list[SearchResult]:
    """Nearest neighbours of a published version, excluding itself."""
    source = session.scalar(
        select(WorkEmbedding).where(WorkEmbedding.work_version_id == work_version_id)
    )
    if source is None:
        return []

    distance = WorkEmbedding.embedding.cosine_distance(source.embedding)
    stmt = (
        _visible_works()
        .join(WorkEmbedding, WorkEmbedding.work_version_id == WorkVersion.id)
        .where(WorkEmbedding.work_version_id != work_version_id)
        .add_columns(distance.label("distance"))
        .order_by(distance)
        .limit(limit)
    )
    return [
        SearchResult(
            work=work, version=version, score=max(0.0, 1.0 - float(dist)), matched_by="similar"
        )
        for work, version, dist in session.execute(stmt).all()
    ]


def index_version(session: Session, *, work: Work, version: WorkVersion) -> WorkEmbedding:
    """Writes or refreshes the vector for a published version."""
    provider = embeddings.get_provider()
    params = version.reusable_params_json or {}
    corpus = " ".join(
        str(part)
        for part in (
            version.title,
            version.description or "",
            params.get("prompt", ""),
            " ".join(params.get("style_tags", []) or []),
        )
        if part
    )
    vector = provider.embed(corpus)

    existing = session.scalar(
        select(WorkEmbedding).where(
            WorkEmbedding.work_version_id == version.id,
            WorkEmbedding.provider == provider.name,
        )
    )
    if existing is not None:
        existing.embedding = vector
        session.flush()
        return existing

    record = WorkEmbedding(
        work_id=work.id,
        work_version_id=version.id,
        provider=provider.name,
        embedding=vector,
    )
    session.add(record)
    session.flush()
    return record
