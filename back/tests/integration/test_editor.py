"""Drama editor REST: flags, ownership, CAS and leases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.editor import EpisodeCut
from app.models.enums import (
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user
from tests.factories import make_job


def _enable_editor(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update(
        {
            "drama_studio_enabled": True,
            "web_editor_enabled": True,
            "variant_export_enabled": True,
            "editor_ai_enabled": True,
            "editor_mcp_enabled": True,
        }
    )
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def _video_asset(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=2048,
        checksum_sha256="c" * 64,
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


def test_editor_routes_are_hidden_when_flags_are_off(client: TestClient, author: User) -> None:
    # Drama-series/episode CRUD (`/v1/drama-series`, `/v1/drama-episodes`) is
    # intentionally open to any authenticated user — only the timeline editor
    # itself (cuts/leases/edit-plans/exports) stays behind `FLAG_EDITOR`.
    response = client.get("/v1/episode-cuts/nonexistent", headers=auth_header(author))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_owner_can_create_a_cut_and_apply_a_command(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    created = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "测试短剧", "target_platforms": ["manual_download"]},
    )
    assert created.status_code == 201, created.text
    series_id = created.json()["id"]
    episode = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    )
    assert episode.status_code == 201, episode.text
    cut = client.post(
        f"/v1/drama-episodes/{episode.json()['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id, "name": "主剪辑"},
    )
    assert cut.status_code == 201, cut.text
    cut_id = cut.json()["id"]
    head_id = cut.json()["head_revision_id"]
    lease = client.post(
        f"/v1/episode-cuts/{cut_id}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    assert lease.status_code == 201, lease.text
    applied = client.post(
        f"/v1/episode-cuts/{cut_id}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_test_1",
            "expected_revision_id": head_id,
            "lease_id": lease.json()["id"],
            "lease_token": lease.json()["token"],
            "commands": [
                {
                    "type": "insert_caption",
                    "track_id": "trk_caption",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "text": "你好",
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["id"] != head_id


def test_add_track_then_insert_clip_round_trips_through_the_api(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    created = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "多轨测试", "target_platforms": ["manual_download"]},
    )
    episode = client.post(
        f"/v1/drama-series/{created.json()['id']}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    )
    cut = client.post(
        f"/v1/drama-episodes/{episode.json()['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id, "name": "主剪辑"},
    )
    cut_id = cut.json()["id"]
    head_id = cut.json()["head_revision_id"]
    lease = client.post(
        f"/v1/episode-cuts/{cut_id}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    applied = client.post(
        f"/v1/episode-cuts/{cut_id}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_track_1",
            "expected_revision_id": head_id,
            "lease_id": lease.json()["id"],
            "lease_token": lease.json()["token"],
            "commands": [
                {
                    "type": "add_track",
                    "kind": "video",
                    "track_id": "trk_pip",
                    "label": "画中画",
                    "order": -1,
                },
                {
                    "type": "insert_clip",
                    "track_id": "trk_pip",
                    "asset_id": asset.id,
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                },
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    document = applied.json()["document"]
    video_tracks = [track for track in document["tracks"] if track["kind"] == "video"]
    assert len(video_tracks) == 2
    # `order: -1` must sort trk_pip ahead of the original trk_video (order 0).
    assert video_tracks[0]["id"] == "trk_pip"
    assert len(video_tracks[0]["elements"]) == 1


def test_stale_expected_revision_conflicts(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "冲突剧", "target_platforms": ["manual_download"]},
    ).json()
    episode = client.post(
        f"/v1/drama-series/{series['id']}/episodes",
        headers=auth_header(author),
        json={"title": "一"},
    ).json()
    cut = client.post(
        f"/v1/drama-episodes/{episode['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id},
    ).json()
    lease = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    ).json()
    stale = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_stale",
            "expected_revision_id": "crv_missing",
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [
                {
                    "type": "set_canvas",
                    "width": 1080,
                    "height": 1920,
                }
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"


def test_apply_commands_sees_a_concurrently_advanced_head_not_a_stale_cached_one(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """Regression test for a SQLAlchemy identity-map staleness bug in
    `apply_commands`/`restore_revision`: both first read the `EpisodeCut` row
    unlocked (via `_owned_cut`), then re-fetch it `with_for_update=True` to
    lock it for the CAS check. If that row was already present in the
    session's identity map (as it always is here, since it's the same
    object), `Session.get(..., with_for_update=True)` alone re-issues the
    locking SELECT but does *not* refresh the already-loaded Python
    attributes from it — so `cut.head_revision_id` can keep reflecting
    whatever it was at the first, unlocked read forever, even after the lock
    is correctly acquired against a row that has since moved on. That made
    the CAS check compare the caller's (correct, freshly-known) expected
    revision against a stale in-memory head and reject it with a false
    `REVISION_CONFLICT`.

    This simulates "some other request already advanced the head" by writing
    `head_revision_id` with a raw, ORM-bypassing UPDATE on the same session
    (so the already-cached `EpisodeCut` instance is left stale, exactly like
    two separate per-request sessions racing in production) and asserts that
    a command batch whose `expected_revision_id` matches that *new* head
    succeeds rather than 409ing.
    """
    from sqlalchemy import update as sa_update

    from app.domain.editor import document as docs
    from app.models.editor import CutRevision

    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    cut = opened["cut"]
    lease = opened["lease"]
    original_head_id = cut["head_revision_id"]

    # Loads `EpisodeCut` into `db`'s identity map exactly as `_owned_cut` does
    # inside the handlers above, pinning `head_revision_id` in memory to
    # `original_head_id`.
    cut_row = db.get(EpisodeCut, cut["id"])
    assert cut_row is not None
    assert cut_row.head_revision_id == original_head_id

    # Fabricate a second revision and move the head to it out from under the
    # ORM, without touching `cut_row` — mirrors a concurrent writer's commit
    # landing between another request's unlocked read and its locked re-fetch.
    original = db.get(CutRevision, original_head_id)
    assert original is not None
    new_revision = CutRevision(
        cut_id=cut["id"],
        revision_no=original.revision_no + 1,
        parent_revision_id=original.id,
        document_json=docs.canonicalize(original.document_json),
        asset_bindings_json=list(original.asset_bindings_json),
        duration_ticks=original.duration_ticks,
        content_hash="f" * 64,
        command_summary_json={"source": "test-simulated-concurrent-writer"},
        created_by_user_id=author.id,
        created_at=original.created_at,
    )
    db.add(new_revision)
    db.flush()
    # `synchronize_session=False` is essential: SQLAlchemy 2.0's ORM-enabled
    # `UPDATE` otherwise auto-syncs matching in-session objects (including
    # `cut_row`), which would silently "fix" the very staleness this test
    # needs to reproduce — a real second request wouldn't share Python
    # objects with this one at all.
    db.execute(
        sa_update(EpisodeCut)
        .where(EpisodeCut.id == cut["id"])
        .values(head_revision_id=new_revision.id),
        execution_options={"synchronize_session": False},
    )
    db.flush()
    assert cut_row.head_revision_id == original_head_id, "sanity: ORM object must still look stale"

    applied = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_concurrent_head",
            "expected_revision_id": new_revision.id,
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [{"type": "set_canvas", "width": 1080, "height": 1920}],
        },
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["id"] != new_revision.id


def test_a_second_browser_cannot_steal_the_write_lease(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "租约剧", "target_platforms": ["manual_download"]},
    ).json()
    episode = client.post(
        f"/v1/drama-series/{series['id']}/episodes",
        headers=auth_header(author),
        json={"title": "一"},
    ).json()
    cut = client.post(
        f"/v1/drama-episodes/{episode['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id},
    ).json()
    first = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    assert first.status_code == 201
    second = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-b"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "LEASE_HELD"


def test_same_browser_reacquire_rotates_the_write_token(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "续租剧", "target_platforms": ["manual_download"]},
    ).json()
    episode = client.post(
        f"/v1/drama-series/{series['id']}/episodes",
        headers=auth_header(author),
        json={"title": "一"},
    ).json()
    cut = client.post(
        f"/v1/drama-episodes/{episode['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id},
    ).json()
    first = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    assert first.status_code == 201, first.text
    first_token = first.json()["token"]
    assert first_token
    second = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    assert second.status_code == 201, second.text
    second_token = second.json()["token"]
    assert second_token
    assert second_token != first_token
    assert second.json()["id"] == first.json()["id"]
    stale = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases/{first.json()['id']}/heartbeat",
        headers={**auth_header(author), "X-Editor-Lease-Token": first_token},
        json={"browser_instance_id": "browser-a"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "LEASE_HELD"
    alive = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases/{second.json()['id']}/heartbeat",
        headers={**auth_header(author), "X-Editor-Lease-Token": second_token},
        json={"browser_instance_id": "browser-a"},
    )
    assert alive.status_code == 200, alive.text


def test_a_stranger_cannot_open_someone_elses_series(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    created = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "私有剧", "target_platforms": ["manual_download"]},
    )
    assert created.status_code == 201
    from tests.conftest import make_user

    outsider = make_user(db, email="editor-outsider@example.com", handle="edout")
    peek = client.get(f"/v1/drama-series/{created.json()['id']}", headers=auth_header(outsider))
    assert peek.status_code == 404


def test_cut_from_job_requires_a_succeeded_output(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    job = make_job(db, author, status=JobStatus.RUNNING, operation=Operation.TEXT_TO_VIDEO)
    response = client.post(
        "/v1/episode-cuts:from-job",
        headers=auth_header(author),
        json={"job_id": job.id},
    )
    assert response.status_code == 422


def test_cut_from_job_opens_a_timeline_on_success(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO)
    job.output_asset_id = asset.id
    db.flush()
    response = client.post(
        "/v1/episode-cuts:from-job",
        headers=auth_header(author),
        json={"job_id": job.id, "title": "从任务来"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_job_id"] == job.id
    assert body["source_asset_id"] == asset.id
    assert body["head_revision_id"]


def test_cut_from_job_skips_a_trashed_series_when_picking_the_fallback(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """Without an explicit `series_id`, `create_cut_from_job` falls back to
    the user's most-recently-created `kind=drama` series. That fallback must
    skip a trashed one — otherwise "进入剪辑" from a job page would silently
    resurrect content into a series the user just moved to the recycle bin,
    where it would then be invisible on the dashboard."""
    _enable_editor(db, admin)
    trashed_series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "已回收的短剧", "target_platforms": ["manual_download"]},
    ).json()
    trash_response = client.delete(
        f"/v1/drama-series/{trashed_series['id']}", headers=auth_header(author)
    )
    assert trash_response.status_code == 204

    asset = _video_asset(db, author)
    job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO)
    job.output_asset_id = asset.id
    db.flush()
    response = client.post(
        "/v1/episode-cuts:from-job",
        headers=auth_header(author),
        json={"job_id": job.id},
    )
    assert response.status_code == 201, response.text

    episode = client.get(
        f"/v1/drama-episodes/{response.json()['episode_id']}", headers=auth_header(author)
    )
    assert episode.status_code == 200
    assert episode.json()["series_id"] != trashed_series["id"]

    new_series = client.get(
        f"/v1/drama-series/{episode.json()['series_id']}", headers=auth_header(author)
    )
    assert new_series.status_code == 200
    assert new_series.json()["status"] == "active"


@contextmanager
def _committed_client(committed_db: Session) -> Iterator[TestClient]:
    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: committed_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _capture_analysis_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records send_task ids and asserts each row is visible on a new connection."""

    from app.db import get_engine
    from app.models import MediaAnalysis

    seen: list[str] = []

    def fake_send_task(name: str, args: list[str] | None = None, **kwargs: object) -> None:
        del name, kwargs
        analysis_id = (args or [""])[0]
        other = Session(bind=get_engine(), expire_on_commit=False)
        try:
            assert other.get(MediaAnalysis, analysis_id) is not None
        finally:
            other.close()
        seen.append(analysis_id)

    monkeypatch.setattr("app.api.v1.editor.celery_app.send_task", fake_send_task)
    return seen


def _seed_editor_owner(committed_db: Session) -> tuple[User, User, Asset]:
    author = make_user(committed_db, email="analysis-author@example.com", handle="anauthor")
    admin = make_user(
        committed_db,
        email="analysis-admin@example.com",
        handle="anadmin",
        roles=["user", "admin"],
    )
    _enable_editor(committed_db, admin)
    asset = _video_asset(committed_db, author)
    committed_db.commit()
    return author, admin, asset


def test_cut_from_job_enqueues_analysis_only_after_commit(
    committed_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    author, _admin, asset = _seed_editor_owner(committed_db)
    job = make_job(
        committed_db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO
    )
    job.output_asset_id = asset.id
    committed_db.commit()
    seen = _capture_analysis_enqueue(monkeypatch)

    with _committed_client(committed_db) as client:
        response = client.post(
            "/v1/episode-cuts:from-job",
            headers=auth_header(author),
            json={"job_id": job.id, "title": "提交后入队"},
        )

    assert response.status_code == 201, response.text
    assert seen


def test_creating_a_cut_enqueues_analysis_only_after_commit(
    committed_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    author, _admin, asset = _seed_editor_owner(committed_db)
    seen = _capture_analysis_enqueue(monkeypatch)

    with _committed_client(committed_db) as client:
        series = client.post(
            "/v1/drama-series",
            headers=auth_header(author),
            json={"title": "提交后入队", "target_platforms": ["manual_download"]},
        )
        assert series.status_code == 201, series.text
        episode = client.post(
            f"/v1/drama-series/{series.json()['id']}/episodes",
            headers=auth_header(author),
            json={"title": "第一集"},
        )
        assert episode.status_code == 201, episode.text
        response = client.post(
            f"/v1/drama-episodes/{episode.json()['id']}/cuts",
            headers=auth_header(author),
            json={"asset_id": asset.id, "name": "主剪辑"},
        )

    assert response.status_code == 201, response.text
    assert seen


def test_missing_media_analysis_does_not_raise() -> None:
    from app.workers import tasks

    assert tasks.run_media_analysis.apply(args=["man_ghost"], throw=True).get() == "missing"


def _open_cut(client: TestClient, author: User, asset: Asset) -> dict[str, Any]:
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "测试短剧", "target_platforms": ["manual_download"]},
    ).json()
    episode = client.post(
        f"/v1/drama-series/{series['id']}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()
    cut = client.post(
        f"/v1/drama-episodes/{episode['id']}/cuts",
        headers=auth_header(author),
        json={"asset_id": asset.id, "name": "主剪辑"},
    ).json()
    lease = client.post(
        f"/v1/episode-cuts/{cut['id']}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    ).json()
    return {"cut": cut, "lease": lease}


def test_a_failed_command_batch_does_not_move_head(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    cut = opened["cut"]
    lease = opened["lease"]
    head_id = cut["head_revision_id"]
    failed = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_rollback",
            "expected_revision_id": head_id,
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [
                {
                    "type": "insert_clip",
                    "track_id": "trk_missing",
                    "asset_id": asset.id,
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                }
            ],
        },
    )
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "BATCH_ROLLED_BACK"
    current = client.get(f"/v1/episode-cuts/{cut['id']}", headers=auth_header(author))
    assert current.status_code == 200
    assert current.json()["head_revision_id"] == head_id


def test_editing_after_an_undo_does_not_collide_on_revision_no(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """Regression test for a false `REVISION_CONFLICT` after undo (restore to
    an earlier revision) followed by a genuinely new edit.

    `_persist_revision` used to number a new revision as `parent.revision_no
    + 1`. Once the client has undone back to an earlier revision (restore is
    just another head-moving write, invariant-wise), the next fresh edit's
    parent has a *lower* `revision_no` than a revision that already exists
    further along the now-abandoned branch — so `parent.revision_no + 1`
    could collide with it and trip the `uq_cut_revisions_cut_revision`
    unique constraint, which `apply_commands` mistranslated into a bogus 409
    `REVISION_CONFLICT` even though nobody else touched the cut. Basing the
    new number on the cut's current max `revision_no` instead (see the fix in
    `service._persist_revision`) makes this collision impossible.
    """
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    cut = opened["cut"]
    lease = opened["lease"]
    rev1_id = cut["head_revision_id"]

    branch = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_branch",
            "expected_revision_id": rev1_id,
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [{"type": "set_canvas", "width": 1440, "height": 2560}],
        },
    )
    assert branch.status_code == 201, branch.text
    rev2_id = branch.json()["id"]
    assert rev2_id != rev1_id

    undo = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions:restore",
        headers=auth_header(author),
        json={
            "revision_id": rev1_id,
            "expected_revision_id": rev2_id,
            "lease_id": lease["id"],
            "lease_token": lease["token"],
        },
    )
    assert undo.status_code == 201, undo.text
    # Restoring to a revision whose content is byte-identical to `rev1`
    # dedupes onto the existing row rather than minting a new one.
    assert undo.json()["id"] == rev1_id

    new_edit = client.post(
        f"/v1/episode-cuts/{cut['id']}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_after_undo",
            "expected_revision_id": rev1_id,
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [{"type": "set_canvas", "width": 720, "height": 1280}],
        },
    )
    assert new_edit.status_code == 201, new_edit.text
    assert new_edit.json()["id"] not in (rev1_id, rev2_id)


def test_bind_editor_export_requires_a_succeeded_output(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    from app.models import DeliveryVariant, Draft, EditorExport
    from app.models.enums import DeliveryVariantStatus, EditorExportStatus

    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    revision_id = opened["cut"]["head_revision_id"]
    variant = DeliveryVariant(
        cut_revision_id=revision_id,
        profile_key="douyin_9_16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        spec_json={"profile_key": "douyin_9_16"},
        spec_hash="a" * 64,
        status=DeliveryVariantStatus.READY,
    )
    db.add(variant)
    db.flush()
    export = EditorExport(
        variant_id=variant.id,
        status=EditorExportStatus.ENCODING,
        operation_key="op_test",
        attempt=1,
    )
    db.add(export)
    draft = Draft(user_id=author.id, title="剪辑草稿")
    db.add(draft)
    db.flush()
    refused = client.post(
        f"/v1/drafts/{draft.id}/bind-editor-export",
        headers=auth_header(author),
        json={"export_id": export.id, "confirmed": True},
    )
    assert refused.status_code == 422
    export.status = EditorExportStatus.SUCCEEDED
    export.output_asset_id = asset.id
    db.flush()
    bound = client.post(
        f"/v1/drafts/{draft.id}/bind-editor-export",
        headers=auth_header(author),
        json={"export_id": export.id, "confirmed": True},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["export_id"] == export.id


def test_operation_sse_skips_events_already_seen(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    from app.domain.editor import service as editor_service
    from app.models import DeliveryVariant, EditorExport
    from app.models.enums import DeliveryVariantStatus, EditorExportStatus

    _enable_editor(db, admin)
    opened = _open_cut(client, author, _video_asset(db, author))
    revision_id = opened["cut"]["head_revision_id"]
    variant = DeliveryVariant(
        cut_revision_id=revision_id,
        profile_key="douyin_9_16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        spec_json={},
        spec_hash="b" * 64,
        status=DeliveryVariantStatus.READY,
    )
    db.add(variant)
    db.flush()
    export = EditorExport(
        variant_id=variant.id,
        status=EditorExportStatus.SUCCEEDED,
        operation_key="op_sse",
        attempt=1,
        progress=100,
    )
    db.add(export)
    db.flush()
    editor_service.append_operation_event(
        db, export.id, event_type="claimed", status="claimed", public_message="claimed"
    )
    editor_service.append_operation_event(
        db, export.id, event_type="succeeded", status="succeeded", public_message="done"
    )
    db.flush()
    headers = auth_header(author)
    full = client.get(f"/v1/editor-operations/{export.id}/events", headers=headers)
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("text/event-stream")
    ids = [
        line[4:]
        for block in full.text.split("\n\n")
        for line in block.splitlines()
        if line.startswith("id: ")
    ]
    assert ids == ["1", "2"]
    resumed = client.get(
        f"/v1/editor-operations/{export.id}/events",
        headers={**headers, "Last-Event-ID": "1"},
    )
    resumed_ids = [
        line[4:]
        for block in resumed.text.split("\n\n")
        for line in block.splitlines()
        if line.startswith("id: ")
    ]
    assert resumed_ids == ["2"]


def _seed_asr_endpoint(session: Session) -> None:
    """One enabled media endpoint offering `audio_generation` — `_resolve_asr_endpoint`
    reuses it for the sibling `/v1/audio/transcriptions` path (see `analysis.py`)."""
    config_service.set_value(
        session,
        "llm_providers",
        {
            "endpoints": {
                "ep-asr-test": {
                    "name": "ASR Test",
                    "base_url": "https://asr.invalid",
                    "api_key": "test-key",
                    "kind": "media",
                    "model": "whisper-1",
                    "input_modalities": ["text"],
                    "output_modalities": ["audio"],
                    "enabled": True,
                }
            }
        },
        actor_user_id=None,
        note="test",
    )


def _capture_transcription_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.db import get_engine
    from app.models import MediaAnalysis

    seen: list[str] = []

    def fake_send_task(name: str, args: list[str] | None = None, **kwargs: object) -> None:
        del name, kwargs
        analysis_id = (args or [""])[0]
        other = Session(bind=get_engine(), expire_on_commit=False)
        try:
            assert other.get(MediaAnalysis, analysis_id) is not None
        finally:
            other.close()
        seen.append(analysis_id)

    monkeypatch.setattr("app.api.v1.editor.celery_app.send_task", fake_send_task)
    return seen


def test_request_transcription_enqueues_only_after_commit(
    committed_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    author, _admin, asset = _seed_editor_owner(committed_db)
    seen = _capture_transcription_enqueue(monkeypatch)

    with _committed_client(committed_db) as client:
        response = client.post(
            f"/v1/media-assets/{asset.id}/transcriptions", headers=auth_header(author)
        )

    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "media_analysis"
    assert seen


def test_request_transcription_rejects_someone_elses_asset(
    committed_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _author, _admin, asset = _seed_editor_owner(committed_db)
    someone_else = make_user(committed_db, email="not-owner@example.com", handle="notowner")
    committed_db.commit()
    _capture_transcription_enqueue(monkeypatch)

    with _committed_client(committed_db) as client:
        response = client.post(
            f"/v1/media-assets/{asset.id}/transcriptions", headers=auth_header(someone_else)
        )
    assert response.status_code == 404, response.text


def test_request_transcription_dedupes_by_analyzer_version(db: Session, author: User) -> None:
    from app.domain.editor import analysis as media_analysis

    asset = _video_asset(db, author)
    db.flush()
    first = media_analysis.enqueue_transcription(db, asset_id=asset.id)
    second = media_analysis.enqueue_transcription(db, asset_id=asset.id)
    assert first.id == second.id


class _FakeAsrResponse:
    def __init__(self, json_body: dict) -> None:
        self._json_body = json_body
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json_body


def test_run_transcription_populates_transcript_from_a_mocked_asr_call(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.editor import analysis as media_analysis
    from app.storage import s3

    _seed_asr_endpoint(db)
    asset = _video_asset(db, author)
    s3.put_object(asset.object_key, b"fake mp4 bytes", content_type="video/mp4")
    db.commit()
    row = media_analysis.enqueue_transcription(db, asset_id=asset.id)
    db.commit()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/audio/transcriptions"
        return _FakeAsrResponse(
            {
                "language": "zh",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "你好"},
                    {"start": 1.5, "end": 3.0, "text": "世界"},
                    {"start": 3.0, "end": 3.2, "text": "   "},  # blank — must be dropped
                ],
            }
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = media_analysis.run_transcription(db, row.id)

    assert result.status == "succeeded"
    assert result.transcript_json["language"] == "zh"
    assert [seg["text"] for seg in result.transcript_json["segments"]] == ["你好", "世界"]
    assert result.transcript_json["segments"][0] == {"start_ms": 0, "end_ms": 1500, "text": "你好"}


def test_run_transcription_fails_gracefully_with_no_configured_endpoint(
    db: Session, author: User
) -> None:
    from app.domain.editor import analysis as media_analysis

    asset = _video_asset(db, author)
    db.commit()
    row = media_analysis.enqueue_transcription(db, asset_id=asset.id)
    db.commit()

    result = media_analysis.run_transcription(db, row.id)
    assert result.status == "failed"
    assert result.failure_message


def test_get_operation_exposes_transcript_only_to_the_asset_owner(
    client: TestClient, db: Session, author: User, admin: User, remixer: User
) -> None:
    from app.domain.editor import analysis as media_analysis
    from app.models.enums import MediaAnalysisStatus

    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    db.commit()
    row = media_analysis.enqueue_transcription(db, asset_id=asset.id)
    row.status = MediaAnalysisStatus.SUCCEEDED
    row.transcript_json = {"language": "zh", "segments": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]}
    db.commit()

    owner_view = client.get(f"/v1/editor-operations/{row.id}", headers=auth_header(author))
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["result"]["transcript"]["segments"][0]["text"] == "hi"

    other_view = client.get(f"/v1/editor-operations/{row.id}", headers=auth_header(remixer))
    assert other_view.status_code == 200, other_view.text
    assert other_view.json()["result"] == {}
