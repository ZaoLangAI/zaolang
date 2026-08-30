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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    Draft,
    DramaEpisode,
    EditorCommandEvent,
    EditorExport,
    EditorLease,
    EditPlan,
    EpisodeContentLink,
    EpisodeCut,
    EpisodeScriptTurn,
    GenerationJob,
    Series,
    User,
    Work,
)
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    DeliveryVariantStatus,
    EditorExportStatus,
    EditPlanStatus,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user
from tests.factories import make_job, make_work


def _enable_editor(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"web_editor_enabled": True})
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def _disable_editor(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"web_editor_enabled": False})
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def _post_episode(client: TestClient, user: User, series_id: str, *, title: str = "第一集") -> str:
    response = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(user),
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _post_cut(client: TestClient, user: User, episode_id: str, asset_id: str) -> dict:
    response = client.post(
        f"/v1/drama-episodes/{episode_id}/cuts",
        headers=auth_header(user),
        json={"asset_id": asset_id, "name": "主剪辑"},
    )
    assert response.status_code == 201, response.text
    return response.json()


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

    response = client.get(f"/v1/drama-episodes/{episode['id']}", headers=auth_header(outsider))
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


def test_delete_episode_cascades_unpublished_cuts(
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
    cut_id = cut.json()["id"]
    revision_id = cut.json()["head_revision_id"]

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text

    fetched = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert fetched.status_code == 404
    assert db.get(EpisodeCut, cut_id) is None
    assert db.get(CutRevision, revision_id) is None


def test_delete_episode_blocked_when_canonical_work_set(
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
    linked = client.post(
        f"/v1/drama-episodes/{episode_id}/set-canonical-work",
        headers=auth_header(author),
        json={"work_id": work.id},
    )
    assert linked.status_code == 200, linked.text

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 422, deleted.text
    still_there = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert still_there.status_code == 200


def _attach_unpublished_export(
    db: Session, *, author: User, revision_id: str, published_work_id: str | None = None
) -> tuple[EditorExport, Draft]:
    variant = DeliveryVariant(
        cut_revision_id=revision_id,
        profile_key="douyin_9_16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        spec_json={"profile_key": "douyin_9_16"},
        spec_hash="c" * 64,
        status=DeliveryVariantStatus.READY,
    )
    db.add(variant)
    db.flush()
    export = EditorExport(
        variant_id=variant.id,
        status=EditorExportStatus.SUCCEEDED,
        operation_key="op_delete_episode",
        attempt=1,
    )
    db.add(export)
    db.flush()
    draft = Draft(
        user_id=author.id,
        title="剪辑草稿",
        editor_export_id=export.id,
        delivery_variant_id=variant.id,
        source_cut_revision_id=revision_id,
        published_work_id=published_work_id,
    )
    db.add(draft)
    db.flush()
    return export, draft


def test_delete_episode_blocked_when_export_bound_to_published_draft(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    work, _version = make_work(db, author)
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
    _attach_unpublished_export(
        db, author=author, revision_id=cut.json()["head_revision_id"], published_work_id=work.id
    )
    db.commit()

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 422, deleted.text
    still_there = client.get(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert still_there.status_code == 200


def test_delete_episode_cascades_unpublished_export_and_clears_draft_pointers(
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
    cut_id = cut.json()["id"]
    revision_id = cut.json()["head_revision_id"]
    export, draft = _attach_unpublished_export(db, author=author, revision_id=revision_id)
    export_id = export.id
    variant_id = export.variant_id
    draft_id = draft.id
    db.commit()

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text

    db.expire_all()
    assert db.get(EpisodeCut, cut_id) is None
    assert db.get(CutRevision, revision_id) is None
    assert db.get(EditorExport, export_id) is None
    assert db.get(DeliveryVariant, variant_id) is None
    leftover = db.get(Draft, draft_id)
    assert leftover is not None
    assert leftover.editor_export_id is None
    assert leftover.delivery_variant_id is None
    assert leftover.source_cut_revision_id is None


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


def test_list_content_links_heals_draft_with_link_episode_id(
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

    first = client.get(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
    )
    assert first.status_code == 200
    link_id = next(
        item["id"]
        for item in first.json()
        if item["content_type"] == "draft" and item["content_ref_id"] == draft_id
    )
    deleted = client.delete(
        f"/v1/drama-episodes/{episode_id}/content-links/{link_id}",
        headers=auth_header(author),
    )
    assert deleted.status_code == 204

    empty = client.get(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
    )
    assert empty.status_code == 200
    assert any(
        item["content_type"] == "draft" and item["content_ref_id"] == draft_id
        for item in empty.json()
    )


def test_delete_episode_works_when_editor_flag_is_off(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """Basic episode CRUD is not `FLAG_EDITOR`-gated. A cut created while
    the flag was on must still be tear-downable after the flag flips off."""
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series_id = _create_series(client, author)
    episode_id = _post_episode(client, author, series_id)
    cut = _post_cut(client, author, episode_id, asset.id)
    _disable_editor(db, admin)

    listed = client.get(f"/v1/drama-episodes/{episode_id}/cuts", headers=auth_header(author))
    assert listed.status_code == 404

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text
    assert db.get(DramaEpisode, episode_id) is None
    assert db.get(EpisodeCut, cut["id"]) is None
    assert db.get(Series, series_id) is not None


def test_delete_episode_leaves_sibling_series_work_asset_and_job(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """Tearing down one unpublished graph must not touch the series, a
    sibling episode, the source asset/job, or an unrelated published work."""
    _enable_editor(db, admin)
    work, _version = make_work(db, author)
    asset = _video_asset(db, author)
    job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO)
    job.output_asset_id = asset.id
    db.flush()

    series_id = _create_series(client, author)
    target_id = _post_episode(client, author, series_id, title="要删的一集")
    sibling_id = _post_episode(client, author, series_id, title="留下的一集")
    cut = _post_cut(client, author, target_id, asset.id)
    export, draft = _attach_unpublished_export(
        db, author=author, revision_id=cut["head_revision_id"]
    )
    db.flush()

    deleted = client.delete(f"/v1/drama-episodes/{target_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text

    db.expire_all()
    assert db.get(DramaEpisode, target_id) is None
    assert db.get(DramaEpisode, sibling_id) is not None
    assert db.get(Series, series_id) is not None
    assert db.get(Work, work.id) is not None
    assert db.get(Asset, asset.id) is not None
    leftover_job = db.get(GenerationJob, job.id)
    assert leftover_job is not None
    assert leftover_job.output_asset_id == asset.id
    leftover_draft = db.get(Draft, draft.id)
    assert leftover_draft is not None
    assert leftover_draft.editor_export_id is None
    assert db.get(EditorExport, export.id) is None

    sibling = client.get(f"/v1/drama-episodes/{sibling_id}", headers=auth_header(author))
    assert sibling.status_code == 200
    listed = client.get(f"/v1/drama-series/{series_id}/episodes", headers=auth_header(author))
    assert {item["id"] for item in listed.json()} == {sibling_id}


def test_delete_episode_cascades_leases_plans_content_links_and_revision_chain(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """`RESTRICT` parents (plans, revision self-refs) and `CASCADE`
    children (leases / command events / content-links) all have to leave
    with the episode, including a two-revision parent chain."""
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series_id = _create_series(client, author)
    episode_id = _post_episode(client, author, series_id)
    cut = _post_cut(client, author, episode_id, asset.id)
    cut_id = cut["id"]
    first_revision_id = cut["head_revision_id"]

    lease = client.post(
        f"/v1/episode-cuts/{cut_id}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-delete"},
    )
    assert lease.status_code == 201, lease.text
    applied = client.post(
        f"/v1/episode-cuts/{cut_id}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_delete_cascade",
            "expected_revision_id": first_revision_id,
            "lease_id": lease.json()["id"],
            "lease_token": lease.json()["token"],
            "commands": [
                {
                    "type": "insert_caption",
                    "track_id": "trk_caption",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "text": "级联",
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    second_revision_id = applied.json()["id"]
    lease_id = lease.json()["id"]

    plan = EditPlan(
        cut_id=cut_id,
        base_revision_id=second_revision_id,
        status=EditPlanStatus.VALIDATED,
        created_by_user_id=author.id,
    )
    db.add(plan)
    db.flush()
    plan_id = plan.id

    linked = client.post(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
        json={"content_type": "draft", "content_ref_id": _orphan_draft(db, author).id},
    )
    assert linked.status_code == 201, linked.text
    link_id = linked.json()["id"]

    event_count = db.scalar(
        select(func.count(EditorCommandEvent.id)).where(EditorCommandEvent.lease_id == lease_id)
    )
    assert event_count and event_count > 0

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text

    db.expire_all()
    assert db.get(EpisodeCut, cut_id) is None
    assert db.get(CutRevision, first_revision_id) is None
    assert db.get(CutRevision, second_revision_id) is None
    assert db.get(EditPlan, plan_id) is None
    assert db.get(EditorLease, lease_id) is None
    assert db.get(EpisodeContentLink, link_id) is None
    assert (
        db.scalar(
            select(func.count(EditorCommandEvent.id)).where(EditorCommandEvent.lease_id == lease_id)
        )
        == 0
    )


def _orphan_draft(db: Session, author: User) -> Draft:
    draft = Draft(user_id=author.id, title="仅作内容关联")
    db.add(draft)
    db.flush()
    return draft


def test_delete_episode_keeps_a_work_that_is_only_a_content_link(
    client: TestClient, db: Session, author: User
) -> None:
    """A `role=candidate` work link is not a published gate. The work
    itself is lineage and must survive the episode going away."""
    work, _version = make_work(db, author)
    db.commit()
    series_id = _create_series(client, author)
    episode_id = _post_episode(client, author, series_id)
    linked = client.post(
        f"/v1/drama-episodes/{episode_id}/content-links",
        headers=auth_header(author),
        json={"content_type": "work", "content_ref_id": work.id, "role": "candidate"},
    )
    assert linked.status_code == 201, linked.text

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text
    db.expire_all()
    assert db.get(Work, work.id) is not None
    assert db.get(DramaEpisode, episode_id) is None


def test_delete_episode_blocked_keeps_work_export_and_draft_pointers(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    work, _version = make_work(db, author)
    asset = _video_asset(db, author)
    series_id = _create_series(client, author)
    episode_id = _post_episode(client, author, series_id)
    cut = _post_cut(client, author, episode_id, asset.id)
    export, draft = _attach_unpublished_export(
        db, author=author, revision_id=cut["head_revision_id"], published_work_id=work.id
    )
    db.commit()

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 422, deleted.text
    assert "已发布成片" in deleted.text

    db.expire_all()
    assert db.get(DramaEpisode, episode_id) is not None
    assert db.get(EpisodeCut, cut["id"]) is not None
    assert db.get(EditorExport, export.id) is not None
    leftover = db.get(Draft, draft.id)
    assert leftover is not None
    assert leftover.editor_export_id == export.id
    assert leftover.published_work_id == work.id
    assert db.get(Work, work.id) is not None


def test_delete_episode_removes_both_cuts_on_the_same_episode(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series_id = _create_series(client, author)
    episode_id = _post_episode(client, author, series_id)
    first = _post_cut(client, author, episode_id, asset.id)
    second = client.post(
        f"/v1/drama-episodes/{episode_id}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id, "name": "预告剪辑", "kind": "trailer"},
    )
    assert second.status_code == 201, second.text

    deleted = client.delete(f"/v1/drama-episodes/{episode_id}", headers=auth_header(author))
    assert deleted.status_code == 204, deleted.text
    db.expire_all()
    assert db.get(EpisodeCut, first["id"]) is None
    assert db.get(EpisodeCut, second.json()["id"]) is None
    assert db.get(CutRevision, first["head_revision_id"]) is None
    assert db.get(CutRevision, second.json()["head_revision_id"]) is None
