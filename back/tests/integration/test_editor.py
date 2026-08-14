"""Drama editor REST: flags, ownership, CAS and leases."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
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
from tests.conftest import auth_header
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
    response = client.get("/v1/drama-series", headers=auth_header(author))
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
        json={"title": "测试短剧"},
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


def test_stale_expected_revision_conflicts(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series", headers=auth_header(author), json={"title": "冲突剧"}
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


def test_a_second_browser_cannot_steal_the_write_lease(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series", headers=auth_header(author), json={"title": "租约剧"}
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


def test_a_stranger_cannot_open_someone_elses_series(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    created = client.post("/v1/drama-series", headers=auth_header(author), json={"title": "私有剧"})
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


def _open_cut(client: TestClient, author: User, asset: Asset) -> dict[str, Any]:
    series = client.post(
        "/v1/drama-series", headers=auth_header(author), json={"title": "测试短剧"}
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
