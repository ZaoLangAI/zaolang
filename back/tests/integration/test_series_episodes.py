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

from app.models import Asset, EpisodeScriptTurn, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user
from tests.factories import make_work


def _enable_editor(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"web_editor_enabled": True})
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def _video_asset(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=2048,
        checksum_sha256="d" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1080,
        height=1920,
        duration_ms=10_000,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _create_series(client: TestClient, user: User) -> str:
    response = client.post(
        "/v1/drama-series",
        headers=auth_header(user),
        json={"title": "我的短剧", "target_platforms": ["manual_download"]},
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
        json={
            "title": "预告片",
            "season_number": 2,
            "episode_number": 1,
            "episode_kind": "trailer",
        },
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


def test_episode_response_reports_has_script_turns(
    client: TestClient, db: Session, author: User
) -> None:
    """`has_script_turns` flags a script-writing shell whose first draft is
    still streaming elsewhere or failed outright, for the series dashboard's
    "待完成剧本" badge — see `script_writing_service.list_scripts`' own
    turn-agnostic filter for why the badge can't just trust `turn_count`
    from that endpoint alone (episode roster and script list are two
    different views)."""
    series_id = _create_series(client, author)

    created = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集", "episode_kind": "main"},
    )
    episode_id = created.json()["id"]

    listed = client.get(f"/v1/drama-series/{series_id}/episodes", headers=auth_header(author))
    assert listed.json()[0]["has_script_turns"] is False

    detail = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert detail.json()["has_script_turns"] is False

    db.add(
        EpisodeScriptTurn(
            episode_id=episode_id,
            turn_no=1,
            parent_turn_id=None,
            user_id=author.id,
            user_message="深夜便利店的秘密",
            summary="s",
            script_snapshot_json={"title": "t", "logline": "l", "characters": [], "scenes": []},
        )
    )
    db.flush()

    listed_after = client.get(f"/v1/drama-series/{series_id}/episodes", headers=auth_header(author))
    assert listed_after.json()[0]["has_script_turns"] is True

    detail_after = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert detail_after.json()["has_script_turns"] is True


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
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "我的短剧项目", "target_platforms": ["manual_download"]},
    )
    assert response.status_code == 201, response.text

    listed = client.get("/v1/drama-series", headers=auth_header(author))
    assert listed.status_code == 200
    assert any(item["title"] == "我的短剧项目" for item in listed.json())


def test_delete_episode_removes_it(client: TestClient, db: Session, author: User) -> None:
    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text

    fetched = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert fetched.status_code == 404

    listed = client.get(f"/v1/drama-series/{series_id}/episodes", headers=auth_header(author))
    assert episode_id not in {item["id"] for item in listed.json()}


def test_delete_episode_blocked_when_cuts_exist(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]
    cut = client.post(
        f"/v1/drama-episodes/{episode_id}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id, "name": "主剪辑"},
    )
    assert cut.status_code == 201, cut.text

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 422, deleted.text

    still_there = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert still_there.status_code == 200


def test_outsider_cannot_delete_someone_elses_episode(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="episode-outsider@example.com", handle="episode-outsider")
    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(outsider))
    assert deleted.status_code == 404


def test_create_draft_with_link_episode_id_writes_content_link(
    client: TestClient, db: Session, author: User
) -> None:
    series_id = _create_series(client, author)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]

    created = client.post(
        "/v1/drafts",
        headers=auth_header(author),
        json={
            "params": {
                "prompt": "值班室",
                "link_episode_id": episode_id,
                "link_breakpoint_key": "内景 值班室#0",
            }
        },
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    assert created.json()["params"]["link_episode_id"] == episode_id
    assert created.json()["params"]["link_breakpoint_key"] == "内景 值班室#0"

    links = client.get(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
    )
    assert links.status_code == 200
    assert any(
        item["content_type"] == "draft" and item["content_ref_id"] == draft_id
        for item in links.json()
    )


def test_create_draft_with_foreign_link_episode_id_still_creates_draft(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="draft-link-outsider@example.com", handle="draft-link-outsider")
    series_id = _create_series(client, outsider)
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(outsider),
        json={"title": "第一集"},
    ).json()["id"]

    created = client.post(
        "/v1/drafts",
        headers=auth_header(author),
        json={"params": {"prompt": "无关", "link_episode_id": episode_id}},
    )
    assert created.status_code == 201, created.text

    links = client.get(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(outsider),
    )
    assert links.status_code == 200
    assert links.json() == []
