"""AC-2 多机位: `…/entries/{entry_id}:orbit`, the per-pose job loop, camera
routing, write-back into pose slots and the auto `camera` edge."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph_service
from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import Asset, CreationSkill, GenerationJob, ProviderAttempt, User
from app.models.base import new_id
from app.models.enums import (
    AssetEntryStatus,
    AssetEntryType,
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.workers import pipeline, tasks
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


def _asset(db: Session, user: User) -> Asset:
    asset = Asset(
        owner_user_id=user.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    return asset


def _card(client: TestClient, db: Session, user: User, kind: str, entry: dict) -> tuple[dict, str]:
    if kind == "characters":
        card = client.post("/v1/characters", json={"name": "林夏"}, headers=auth_header(user))
        variants = card.json()["looks"]
        segment = "looks"
    else:
        card = client.post("/v1/scenes", json={"name": "客厅"}, headers=auth_header(user))
        variants = card.json()["variants"]
        segment = "variants"
    body = card.json()
    created = client.post(
        f"/v1/{kind}/{body['id']}/{segment}/{variants[0]['id']}/entries",
        json={"asset_id": _asset(db, user).id, **entry},
        headers=auth_header(user),
    )
    assert created.status_code == 201, created.text
    return body, created.json()["id"]


def _orbit(
    client: TestClient, user: User, kind: str, card_id: str, entry_id: str, poses: list[dict], **kw
):
    return client.post(
        f"/v1/{kind}/{card_id}/entries/{entry_id}:orbit",
        json={"poses": poses, **kw},
        headers={**auth_header(user), "Idempotency-Key": f"orbit-{entry_id}"},
    )


def test_a_dry_run_prices_one_image_per_pose(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card(
        client, db, author, "scenes", {"entry_type": "master"}
    )
    body = _orbit(
        client, author, "scenes", card["id"], entry_id, [{"azimuth": 180}, {"azimuth": 90}]
    ).json()
    from app.domain.jobs import service as jobs_service

    assert body["credits"] == jobs_service.quote_for(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier="standard", output_count=2
    ).credits
    assert [p["azimuth"] for p in body["poses"]] == [180, 90]
    assert body["job_id"] is None and dispatched == []


def test_a_sheet_source_is_led_by_the_front_figure(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card(client, db, author, "characters", {"entry_type": "character_sheet"})
    body = _orbit(client, author, "characters", card["id"], entry_id, [{"azimuth": 180}]).json()
    assert [p["azimuth"] for p in body["poses"]] == [0, 180]


def test_an_expression_sheet_cannot_be_orbited(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card(
        client,
        db,
        author,
        "characters",
        {"entry_type": "expression_sheet", "expressions": ["smile"]},
    )
    response = _orbit(client, author, "characters", card["id"], entry_id, [{"azimuth": 90}])
    assert response.status_code == 422


def test_someone_elses_entry_is_a_404(
    client: TestClient, db: Session, author: User, remixer: User, dispatched: list[str]
) -> None:
    card, entry_id = _card(client, db, author, "scenes", {"entry_type": "master"})
    response = _orbit(client, remixer, "scenes", card["id"], entry_id, [{"azimuth": 90}])
    assert response.status_code == 404


def test_duplicate_poses_collapse_to_one(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card(client, db, author, "scenes", {"entry_type": "master"})
    body = _orbit(
        client, author, "scenes", card["id"], entry_id, [{"azimuth": 90}, {"azimuth": 100}]
    ).json()
    assert [p["azimuth"] for p in body["poses"]] == [90]


def test_a_scene_orbit_routes_each_pass_to_the_camera_model_and_files_shots(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    card, entry_id = _card(client, db, author, "scenes", {"entry_type": "master"})
    response = _orbit(
        client,
        author,
        "scenes",
        card["id"],
        entry_id,
        [{"azimuth": 180}, {"azimuth": 90, "elevation": 30}],
        dry_run=False,
    )
    assert response.status_code == 200, response.text
    job = db.get(GenerationJob, response.json()["job_id"])
    assert job is not None and job.operation == Operation.IMAGE_TO_IMAGE
    assert dispatched == [job.id]
    skill = db.get(CreationSkill, card["id"])
    source = av.find_entry(skill, entry_id)
    assert job.request_json["reference_asset_ids"][0] == source.asset_id

    outcome = pipeline.run_generation_pipeline(db, job.id)
    assert outcome.status == JobStatus.SUCCEEDED

    attempts = db.query(ProviderAttempt).filter_by(job_id=job.id).all()
    assert {a.provider for a in attempts if a.status == "succeeded"} == {"fake_camera_api"}
    db.expire_all()
    skill = db.get(CreationSkill, card["id"])
    shots = [e for e in av.entries(skill) if e.source_job_id == job.id]
    assert sorted((e.camera_json["azimuth"], e.view) for e in shots) == [(90, None), (180, "reverse")]
    assert all(e.entry_type == AssetEntryType.SHOT for e in shots)
    assert all(e.status == AssetEntryStatus.APPROVED for e in shots)
    edges = graph_service.edges(db, skill)
    assert sorted(edge.relations_json[0] for edge in edges) == ["camera", "camera"]
    assert {edge.label for edge in edges} == {"背面 180°·平视·中景", "右侧 90°·俯拍·中景"}


def test_a_sheet_orbit_extracts_the_front_figure_first_then_chains_it(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    card, entry_id = _card(client, db, author, "characters", {"entry_type": "character_sheet"})
    response = _orbit(
        client, author, "characters", card["id"], entry_id, [{"azimuth": 270}], dry_run=False
    )
    job = db.get(GenerationJob, response.json()["job_id"])
    assert job is not None and job.request_json["camera_from_sheet"] is True

    outcome = pipeline.run_generation_pipeline(db, job.id)
    assert outcome.status == JobStatus.SUCCEEDED

    attempts = (
        db.query(ProviderAttempt)
        .filter_by(job_id=job.id, status="succeeded")
        .order_by(ProviderAttempt.attempt_number)
        .all()
    )
    # Pass 1 (the front figure out of the sheet) never goes to the camera
    # route; pass 2 does.
    assert [a.provider == "fake_camera_api" for a in attempts] == [False, True]
    db.expire_all()
    skill = db.get(CreationSkill, card["id"])
    views = sorted(
        (e for e in av.entries(skill) if e.source_job_id == job.id),
        key=lambda e: e.camera_json["azimuth"],
    )
    assert [(e.entry_type, e.view, e.camera_json["azimuth"]) for e in views] == [
        (AssetEntryType.VIEW, "front", 0),
        (AssetEntryType.VIEW, "side", 270),
    ]
