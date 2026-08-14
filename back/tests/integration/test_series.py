"""The series list endpoint that backs the create page's "recent series" rail.

`GET /v1/series` has to do two things the plain CRUD rows cannot answer on
their own: sort by which series was actually worked on most recently, and
carry enough about the latest episode (cover, number) that the rail can
render a "continue episode N" card without a second round trip per series.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, Series, User, Work, WorkVersion
from app.models.base import new_id, utcnow
from app.models.enums import AssetRole, MediaType, ModerationStatus, SeriesKind, Visibility
from tests.conftest import auth_header


def _series(session: Session, owner: User, *, title: str = "深夜食堂") -> Series:
    series = Series(owner_user_id=owner.id, title=title, character_ids_json=[])
    session.add(series)
    session.flush()
    return series


def _cover_asset(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.jpg",
        media_type=MediaType.IMAGE,
        mime_type="image/jpeg",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _episode(
    session: Session,
    owner: User,
    series: Series,
    *,
    episode_number: int,
    title: str,
    published_at: dt.datetime,
    cover_asset: Asset | None = None,
) -> Work:
    work = Work(
        owner_user_id=owner.id,
        series_id=series.id,
        episode_number=episode_number,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        published_at=published_at,
    )
    session.add(work)
    session.flush()

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        cover_asset_id=cover_asset.id if cover_asset else None,
        immutable_created_at=published_at,
    )
    session.add(version)
    session.flush()

    work.current_version_id = version.id
    session.flush()
    return work


def test_list_series_sorts_by_latest_episode_activity(
    db: Session, client: TestClient, author: User
) -> None:
    now = utcnow()
    stale = _series(db, author, title="老系列")
    _episode(
        db,
        author,
        stale,
        episode_number=1,
        title="第一集",
        published_at=now - dt.timedelta(days=10),
    )

    fresh = _series(db, author, title="新系列")
    _episode(
        db,
        author,
        fresh,
        episode_number=1,
        title="第一集",
        published_at=now - dt.timedelta(days=1),
    )

    # Never published: falls back to the series row's own `created_at`, which
    # is newer than either episode above.
    untouched = _series(db, author, title="刚创建")
    db.commit()

    response = client.get("/v1/series", headers=auth_header(author))
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()]
    assert ids == [untouched.id, fresh.id, stale.id]


def test_list_series_reports_episode_count_and_latest_episode(
    db: Session, client: TestClient, author: User
) -> None:
    series = _series(db, author, title="潮汐")
    cover = _cover_asset(db, author)
    _episode(db, author, series, episode_number=1, title="第一集", published_at=utcnow())
    latest = _episode(
        db,
        author,
        series,
        episode_number=2,
        title="第二集",
        published_at=utcnow(),
        cover_asset=cover,
    )
    db.commit()

    response = client.get("/v1/series", headers=auth_header(author))
    assert response.status_code == 200
    body = next(item for item in response.json() if item["id"] == series.id)
    assert body["episode_count"] == 2
    assert body["latest_episode"]["work_id"] == latest.id
    assert body["latest_episode"]["episode_number"] == 2
    assert body["latest_episode"]["cover_url"] is not None


def test_list_series_without_episodes_has_default_counts(
    db: Session, client: TestClient, author: User
) -> None:
    series = _series(db, author, title="空系列")
    db.commit()

    response = client.get("/v1/series", headers=auth_header(author))
    assert response.status_code == 200
    body = next(item for item in response.json() if item["id"] == series.id)
    assert body["episode_count"] == 0
    assert body["latest_episode"] is None


def test_list_series_only_returns_the_caller_own_series(
    db: Session, client: TestClient, author: User, remixer: User
) -> None:
    _series(db, remixer, title="别人的系列")
    db.commit()

    response = client.get("/v1/series", headers=auth_header(author))
    assert response.status_code == 200
    assert response.json() == []


def test_list_and_get_series_exclude_drama_projects(
    db: Session, client: TestClient, author: User
) -> None:
    """Drama rows share `series` but must not leak into the cast-roster API."""
    roster = _series(db, author, title="角色名册")
    drama = Series(
        owner_user_id=author.id,
        title="短剧制作",
        character_ids_json=[],
        kind=SeriesKind.DRAMA,
    )
    db.add(drama)
    db.commit()

    listed = client.get("/v1/series", headers=auth_header(author))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [roster.id]

    hidden = client.get(f"/v1/series/{drama.id}", headers=auth_header(author))
    assert hidden.status_code == 404

    visible = client.get(f"/v1/series/{roster.id}", headers=auth_header(author))
    assert visible.status_code == 200
    assert visible.json()["id"] == roster.id
