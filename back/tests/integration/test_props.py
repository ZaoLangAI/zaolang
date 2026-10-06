"""AC-4 道具: the prop library API, its variants, prop jobs' write-back, prop
references in other jobs, and the graph / orbit routes for props."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.props import service as props_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import Asset, CreationSkill, GenerationJob, User
from app.models.base import new_id
from app.models.enums import (
    AssetEntryType,
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    QualityTier,
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


def test_prop_crud_and_hero_plate(client: TestClient, db: Session, author: User) -> None:
    hero = _asset(db, author)
    created = client.post(
        "/v1/props",
        json={"name": "青铜古剑", "description": "剑身有铭文", "reference_asset_ids": [hero.id]},
        headers=auth_header(author),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["variants"][0]["name"] == "默认状态"
    assert body["reference_assets"][0]["view"] == "hero"
    assert body["variants"][0]["entries"][0]["entry_type"] == "master"
    assert body["anchor_entry_id"] == body["variants"][0]["entries"][0]["id"]

    listed = client.get("/v1/props", headers=auth_header(author)).json()
    assert [p["id"] for p in listed] == [body["id"]]
    renamed = client.patch(
        f"/v1/props/{body['id']}", json={"name": "古剑"}, headers=auth_header(author)
    ).json()
    assert renamed["name"] == "古剑"
    assert client.delete(f"/v1/props/{body['id']}", headers=auth_header(author)).status_code == 204


def test_someone_elses_prop_is_a_404(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    prop = props_service.create_prop(
        db, user_id=author.id, name="剑", description=None, reference_asset_ids=[]
    )
    db.commit()
    assert client.get(f"/v1/props/{prop.id}", headers=auth_header(remixer)).status_code == 404


def test_a_prop_variant_takes_a_condition_preset(
    client: TestClient, db: Session, author: User
) -> None:
    prop = client.post("/v1/props", json={"name": "剑"}, headers=auth_header(author)).json()
    made = client.post(
        f"/v1/props/{prop['id']}/variants",
        json={"name": "破损", "presets": {"prop_state": "damaged"}},
        headers=auth_header(author),
    )
    assert made.status_code in (200, 201), made.text
    assert made.json()["presets"] == {"prop_state": "damaged"}
    bad = client.post(
        f"/v1/props/{prop['id']}/variants",
        json={"name": "黄昏", "presets": {"lighting": "dusk"}},
        headers=auth_header(author),
    )
    assert bad.status_code == 422


def test_the_generic_skill_api_refuses_prop_cards(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/skills",
        json={"title": "剑", "category": "prop_asset", "params": {}},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_a_prop_job_auto_creates_the_card_and_a_state_variant(db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={
            "prompt": "一把青铜古剑",
            "aspect_ratio": "1:1",
            "asset_kind": "prop",
            "subject_name_hint": "青铜古剑",
            "prop_state": "worn",
        },
        idempotency_key=new_id("idk"),
    ).job
    assert pipeline.run_generation_pipeline(db, job.id).status == JobStatus.SUCCEEDED
    db.refresh(job)
    assert job.linked_prop_id is not None
    skill = db.get(CreationSkill, job.linked_prop_id)
    assert skill is not None and skill.title == "青铜古剑"
    worn = av.find_by_name(skill, "旧化")
    assert worn is not None and worn.presets_json == {"prop_state": "worn"}
    assert [e.entry_type for e in worn.entries] == [AssetEntryType.MASTER]


def test_prop_ids_join_the_reference_budget_after_scenes(db: Session, author: User) -> None:
    from app.domain.image_assets import reference_resolver

    hero = _asset(db, author)
    prop = props_service.create_prop(
        db, user_id=author.id, name="剑", description=None, reference_asset_ids=[hero.id]
    )
    params = {"prompt": "x", "prop_ids": [prop.id]}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [hero.id]
    assert params["reference_labels"] == [{"asset_id": hero.id, "label": "道具「剑」·主图"}]


def test_a_prop_graph_and_orbit(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    hero = _asset(db, author)
    prop = client.post(
        "/v1/props",
        json={"name": "剑", "reference_asset_ids": [hero.id]},
        headers=auth_header(author),
    ).json()
    graph = client.get(f"/v1/props/{prop['id']}/graph", headers=auth_header(author))
    assert graph.status_code == 200, graph.text
    assert graph.json()["card_kind"] == "prop"
    entry_id = prop["anchor_entry_id"]
    response = client.post(
        f"/v1/props/{prop['id']}/entries/{entry_id}:orbit",
        json={"poses": [{"azimuth": 90}, {"azimuth": 180}], "dry_run": False},
        headers={**auth_header(author), "Idempotency-Key": "prop-orbit"},
    )
    assert response.status_code == 200, response.text
    job = db.get(GenerationJob, response.json()["job_id"])
    assert job is not None
    assert job.request_json["asset_kind"] == "prop"
    assert job.request_json["target_prop_id"] == prop["id"]
    assert job.request_json["reference_asset_ids"][0] == hero.id
    assert dispatched == [job.id]

    assert pipeline.run_generation_pipeline(db, job.id).status == JobStatus.SUCCEEDED
    db.expire_all()
    skill = db.get(CreationSkill, prop["id"])
    views = sorted(
        (e for e in av.entries(skill) if e.source_job_id == job.id),
        key=lambda e: e.camera_json["azimuth"],
    )
    assert [(e.entry_type, e.view) for e in views] == [
        (AssetEntryType.VIEW, "side"),
        (AssetEntryType.VIEW, "back"),
    ]
