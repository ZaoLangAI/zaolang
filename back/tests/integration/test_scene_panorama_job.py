"""AC-7: a scene panorama job end to end — forced 2:1 at the API, one image,
filed as the target variant's panorama slot (a second one as a candidate)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.domain.scenes import service as scenes_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, AssetEntryType, JobStatus
from app.workers import pipeline, tasks
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


def test_a_panorama_job_files_the_variant_panorama(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: None)
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )

    def submit(key: str) -> GenerationJob:
        response = client.post(
            "/v1/generation-jobs",
            json={
                "operation": "text_to_image",
                "quality_tier": "standard",
                "params": {
                    "prompt": "老式客厅",
                    "aspect_ratio": "16:9",
                    "asset_kind": "scene",
                    "target_scene_id": scene.id,
                    "scene_panorama": True,
                },
            },
            headers={**auth_header(author), "Idempotency-Key": key},
        )
        assert response.status_code == 202, response.text
        job = db.get(GenerationJob, response.json()["id"])
        assert job is not None
        assert job.request_json["aspect_ratio"] == "2:1"
        assert pipeline.run_generation_pipeline(db, job.id).status == JobStatus.SUCCEEDED
        return job

    first = submit("pano-1")
    db.expire_all()
    panoramas = [e for e in av.entries(scene.skill) if e.entry_type == AssetEntryType.PANORAMA]
    assert [e.asset_id for e in panoramas] == [first.output_asset_id]
    assert panoramas[0].status == AssetEntryStatus.APPROVED
    # Never the scene's master or anchor, even as its only image.
    assert av.anchor(scene.skill) is None

    second = submit("pano-2")
    db.expire_all()
    statuses = {
        e.asset_id: e.status
        for e in av.entries(scene.skill)
        if e.entry_type == AssetEntryType.PANORAMA
    }
    assert statuses == {
        first.output_asset_id: AssetEntryStatus.APPROVED,
        second.output_asset_id: AssetEntryStatus.CANDIDATE,
    }
