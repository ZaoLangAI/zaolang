"""Drama series recycle bin (`trash`/`untrash`/`purge`) and the
`list_drama_series` sort-direction parameter — see `zaolang-editor-drama`."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Series, User
from app.models.base import utcnow
from tests.conftest import auth_header, make_user


def _create_series(client: TestClient, user: User, *, title: str = "我的短剧") -> str:
    response = client.post(
        "/v1/drama-series",
        headers=auth_header(user),
        json={"title": title, "target_platforms": ["manual_download"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_sort_dir_toggles_order(client: TestClient, db: Session, author: User) -> None:
    older_id = _create_series(client, author, title="较早的剧集")
    newer_id = _create_series(client, author, title="较新的剧集")
    older = db.get(Series, older_id)
    newer = db.get(Series, newer_id)
    assert older is not None and newer is not None
    older.created_at = utcnow() - dt.timedelta(hours=2)
    newer.created_at = utcnow() - dt.timedelta(hours=1)
    db.commit()

    ascending = client.get(
        "/v1/drama-series",
        headers=auth_header(author),
        params={"sort": "created_at", "sort_dir": "asc"},
    )
    assert ascending.status_code == 200
    ids = [item["id"] for item in ascending.json() if item["id"] in (older_id, newer_id)]
    assert ids == [older_id, newer_id]

    descending = client.get(
        "/v1/drama-series",
        headers=auth_header(author),
        params={"sort": "created_at", "sort_dir": "desc"},
    )
    assert descending.status_code == 200
    ids = [item["id"] for item in descending.json() if item["id"] in (older_id, newer_id)]
    assert ids == [newer_id, older_id]


def test_trash_and_untrash_series_round_trip(client: TestClient, db: Session, author: User) -> None:
    series_id = _create_series(client, author)

    trashed = client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(author))
    assert trashed.status_code == 204, trashed.text

    fetched = client.get(f"/v1/drama-series/{series_id}", headers=auth_header(author))
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "trashed"

    restored = client.post(f"/v1/drama-series/{series_id}/untrash", headers=auth_header(author))
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"


def test_trashed_series_excluded_from_default_list_but_included_with_status_trashed(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)
    client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(author))

    default_list = client.get("/v1/drama-series", headers=auth_header(author))
    assert series_id not in {item["id"] for item in default_list.json()}

    trash_list = client.get(
        "/v1/drama-series", headers=auth_header(author), params={"status": "trashed"}
    )
    assert series_id in {item["id"] for item in trash_list.json()}


def test_purge_series_blocked_while_episodes_exist(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)
    client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    )
    client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(author))

    purged = client.delete(f"/v1/drama-series/{series_id}/purge", headers=auth_header(author))
    assert purged.status_code == 422, purged.text

    still_there = client.get(
        "/v1/drama-series", headers=auth_header(author), params={"status": "trashed"}
    )
    assert series_id in {item["id"] for item in still_there.json()}


def test_purge_series_succeeds_once_episodes_removed(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]
    client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(author))
    deleted_episode = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted_episode.status_code == 204, deleted_episode.text

    purged = client.delete(f"/v1/drama-series/{series_id}/purge", headers=auth_header(author))
    assert purged.status_code == 204, purged.text

    fetched = client.get(f"/v1/drama-series/{series_id}", headers=auth_header(author))
    assert fetched.status_code == 404


def test_purge_requires_series_to_be_trashed_first(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)
    purged = client.delete(f"/v1/drama-series/{series_id}/purge", headers=auth_header(author))
    assert purged.status_code == 409, purged.text


def test_outsider_cannot_trash_or_purge_someone_elses_series(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="series-outsider@example.com", handle="series-outsider")
    series_id = _create_series(client, author)

    trashed = client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(outsider))
    assert trashed.status_code == 404

    client.delete(f"/v1/drama-series/{series_id}", headers=auth_header(author))
    purged = client.delete(f"/v1/drama-series/{series_id}/purge", headers=auth_header(outsider))
    assert purged.status_code == 404
