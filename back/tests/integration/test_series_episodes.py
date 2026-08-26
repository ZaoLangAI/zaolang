"""Unified episode management on `/v1/drama-series`+`/v1/drama-episodes` —
the single surface for drama-series/episode CRUD, content-links, and
canonical-work selection, used by both the roster-based shortform flow and
the desktop drama editor. Series-level CRUD (`/v1/drama-series`) and episode
CRUD (`/v1/drama-episodes`) are both open to any authenticated user; only the
full timeline editor (cuts/leases/edit-plans/exports) stays behind
`FLAG_EDITOR` and friends (see `back/app/domain/editor/service.py`'s module
docstring)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import auth_header, make_user
from tests.factories import make_work


def _create_series(client: TestClient, user: User) -> str:
    response = client.post(
        "/v1/drama-series", headers=auth_header(user), json={"title": "我的短剧"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_episode_crud_works_for_any_authenticated_user(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)

    created = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集", "episode_kind": "main"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["series_id"] == series_id
    assert body["season_number"] == 1
    assert body["episode_number"] == 1
    assert body["episode_kind"] == "main"
    episode_id = body["id"]

    trailer = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "预告片", "season_number": 2, "episode_number": 1, "episode_kind": "trailer"},
    )
    assert trailer.status_code == 201, trailer.text

    listed = client.get(f"/v1/drama-series/{series_id}/episodes", headers=auth_header(author))
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {episode_id, trailer.json()["id"]}

    updated = client.patch(
        f"/v1/drama-episodes/{episode_id}",
        headers=auth_header(author),
        json={"status": "published", "season_number": 3},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "published"
    assert updated.json()["season_number"] == 3


def test_outsider_cannot_manage_someone_elses_episodes(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="outsider@example.com", handle="outsider")
    series_id = _create_series(client, author)
    episode = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()

    response = client.get(
        f"/v1/drama-episodes/{episode['id']}", headers=auth_header(outsider)
    )
    assert response.status_code == 404


def test_content_link_rejects_someone_elses_work(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="outsider2@example.com", handle="outsider2")
    other_work, _version = make_work(db, outsider)
    db.commit()

    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]

    response = client.post(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
        json={"content_type": "work", "content_ref_id": other_work.id, "role": "candidate"},
    )
    assert response.status_code == 403, response.text


def test_set_canonical_work_links_and_marks_final(
    client: TestClient, db: Session, author: User
) -> None:
    work, _version = make_work(db, author)
    db.commit()

    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]

    response = client.post(
        f"/v1/drama-episodes/{episode_id}/set-canonical-work",
        headers=auth_header(author),
        json={"work_id": work.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["canonical_work_id"] == work.id

    links = client.get(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
    )
    assert links.status_code == 200
    assert any(
        link["content_ref_id"] == work.id and link["role"] == "final" for link in links.json()
    )

    cleared = client.post(
        f"/v1/drama-episodes/{episode_id}/set-canonical-work",
        headers=auth_header(author),
        json={"work_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["canonical_work_id"] is None


def test_drama_series_open_to_any_authenticated_user(
    client: TestClient, db: Session, author: User
) -> None:
    response = client.post(
        "/v1/drama-series", headers=auth_header(author), json={"title": "我的短剧项目"}
    )
    assert response.status_code == 201, response.text

    listed = client.get("/v1/drama-series", headers=auth_header(author))
    assert listed.status_code == 200
    assert any(item["title"] == "我的短剧项目" for item in listed.json())
