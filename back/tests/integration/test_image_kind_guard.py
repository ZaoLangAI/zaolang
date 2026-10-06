"""General and cover image generation is retired at the API (AC-8).

Every consumer entry point that can price or start an image job — quote,
batch quote, submit, retry and promote — refuses one that is not a library
asset (character / scene / prop) with `IMAGE_ASSET_KIND_REQUIRED`. The guard
lives in the route layer, not `jobs_service.submit`, because the canvas Agent
still submits general images through the domain.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import JobStatus, Operation, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from app.workers import pipeline
from tests.conftest import auth_header, patch_app_db_session_scope

pytestmark = pytest.mark.usefixtures("fake_media_catalog")

RETIRED_KINDS = ["general", "cover"]
ASSET_KINDS = ["character", "scene", "prop"]


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 100_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


def _assert_refused(response, field: str) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "IMAGE_ASSET_KIND_REQUIRED"
    assert field in error["details"]["fields"]


def _domain_job(db: Session, user: User, *, asset_kind: str | None, tier: QualityTier):
    params: dict[str, object] = {"prompt": "雨后的东京街头", "aspect_ratio": "16:9"}
    if asset_kind is not None:
        params["asset_kind"] = asset_kind
    return jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=tier,
        params=params,
        idempotency_key=new_id("idk"),
    ).job


def _failed_job(db: Session, user: User, *, asset_kind: str | None) -> GenerationJob:
    job = _domain_job(db, user, asset_kind=asset_kind, tier=QualityTier.STANDARD)
    jobs_service.settle_release(db, job, reason="test fail")
    failed = sm.transition(db, job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR")
    db.commit()
    return failed


def _succeeded_preview(db: Session, user: User, *, asset_kind: str | None) -> GenerationJob:
    job = _domain_job(db, user, asset_kind=asset_kind, tier=QualityTier.PREVIEW)
    db.commit()
    pipeline.run_generation_pipeline(db, job.id)
    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    return job


# ---------------------------------------------------------------------------
# quote / quote:batch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", RETIRED_KINDS)
@pytest.mark.parametrize("operation", ["text_to_image", "image_to_image"])
def test_quote_refuses_a_non_asset_image(
    client: TestClient, funded: User, kind: str, operation: str
) -> None:
    response = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": operation, "quality_tier": "standard", "asset_kind": kind},
        headers=auth_header(funded),
    )
    _assert_refused(response, "asset_kind")


def test_quote_refuses_an_image_with_no_kind(client: TestClient, funded: User) -> None:
    response = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": "text_to_image", "quality_tier": "standard"},
        headers=auth_header(funded),
    )
    _assert_refused(response, "asset_kind")


@pytest.mark.parametrize("kind", ASSET_KINDS)
def test_quote_prices_an_asset_image(client: TestClient, funded: User, kind: str) -> None:
    response = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": "text_to_image", "quality_tier": "standard", "asset_kind": kind},
        headers=auth_header(funded),
    )
    assert response.status_code == 200, response.text
    assert response.json()["credits"] > 0


def test_quote_leaves_video_alone(client: TestClient, funded: User) -> None:
    response = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": "text_to_video", "quality_tier": "standard", "duration_seconds": 5},
        headers=auth_header(funded),
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("kind", RETIRED_KINDS)
def test_batch_quote_refuses_any_non_asset_image_line(
    client: TestClient, funded: User, kind: str
) -> None:
    response = client.post(
        "/v1/generation-jobs/quote:batch",
        json={
            "items": [
                {"operation": "text_to_image", "quality_tier": "standard", "asset_kind": "scene"},
                {"operation": "text_to_image", "quality_tier": "standard", "asset_kind": kind},
            ]
        },
        headers=auth_header(funded),
    )
    _assert_refused(response, "items.1.asset_kind")


def test_batch_quote_prices_asset_and_video_lines(client: TestClient, funded: User) -> None:
    response = client.post(
        "/v1/generation-jobs/quote:batch",
        json={
            "items": [
                {"operation": "text_to_image", "quality_tier": "standard", "asset_kind": k}
                for k in ASSET_KINDS
            ]
            + [{"operation": "text_to_video", "quality_tier": "standard", "duration_seconds": 5}]
        },
        headers=auth_header(funded),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 4


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["general", None])
def test_submit_refuses_a_non_asset_image(
    client: TestClient, db: Session, funded: User, kind: str | None
) -> None:
    before = db.query(GenerationJob).count()
    params: dict[str, object] = {"prompt": "雨后的东京街头"}
    if kind is not None:
        params["asset_kind"] = kind
    response = client.post(
        "/v1/generation-jobs",
        json={"operation": "text_to_image", "quality_tier": "standard", "params": params},
        headers=auth_header(funded),
    )
    _assert_refused(response, "params.asset_kind")
    assert db.query(GenerationJob).count() == before


def test_submit_refuses_a_cover_image_before_the_route(
    client: TestClient, db: Session, funded: User
) -> None:
    """`GenerationParams` itself refuses a new `cover` job (the enum value
    stays for historic rows), so the request never reaches the handler."""
    before = db.query(GenerationJob).count()
    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "text_to_image",
            "quality_tier": "standard",
            "params": {"prompt": "短剧封面", "asset_kind": "cover"},
        },
        headers=auth_header(funded),
    )
    assert response.status_code == 422, response.text
    assert "封面图片生成已下线" in response.json()["error"]["message"]
    assert db.query(GenerationJob).count() == before


@pytest.mark.parametrize("kind", ASSET_KINDS)
def test_submit_accepts_an_asset_image(client: TestClient, funded: User, kind: str) -> None:
    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "text_to_image",
            "quality_tier": "standard",
            "params": {"prompt": "雨后的东京街头", "asset_kind": kind},
        },
        headers=auth_header(funded),
    )
    assert response.status_code == 202, response.text
    assert response.json()["asset_kind"] == kind


# ---------------------------------------------------------------------------
# retry / promote read the original request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [None, "cover"])
def test_retry_refuses_a_historic_non_asset_image(
    client: TestClient, db: Session, funded: User, kind: str | None
) -> None:
    original = _failed_job(db, funded, asset_kind=kind)
    response = client.post(f"/v1/generation-jobs/{original.id}/retry", headers=auth_header(funded))
    _assert_refused(response, "params.asset_kind")


def test_retry_resubmits_an_asset_image(client: TestClient, db: Session, funded: User) -> None:
    original = _failed_job(db, funded, asset_kind="scene")
    response = client.post(f"/v1/generation-jobs/{original.id}/retry", headers=auth_header(funded))
    assert response.status_code == 202, response.text


@pytest.mark.parametrize("kind", [None, "general"])
def test_promote_refuses_a_historic_non_asset_image(
    client: TestClient, db: Session, funded: User, kind: str | None
) -> None:
    original = _succeeded_preview(db, funded, asset_kind=kind)
    response = client.post(
        f"/v1/generation-jobs/{original.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(funded),
    )
    _assert_refused(response, "params.asset_kind")


def test_promote_upgrades_an_asset_image(client: TestClient, db: Session, funded: User) -> None:
    original = _succeeded_preview(db, funded, asset_kind="scene")
    response = client.post(
        f"/v1/generation-jobs/{original.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(funded),
    )
    assert response.status_code == 202, response.text


# ---------------------------------------------------------------------------
# The canvas Agent submits general images through the domain
# ---------------------------------------------------------------------------


def test_the_canvas_agent_still_submits_general_images(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, db: Session, funded: User
) -> None:
    patch_app_db_session_scope(monkeypatch, db)
    flags = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    flags["canvas_studio_enabled"] = True
    config_service.set_value(db, "feature_flags", flags, actor_user_id=None, note="test")
    canvas = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(funded)
    ).json()
    client.post(
        f"/v1/canvas-projects/{canvas['id']}/graph-ops",
        json={
            "base_seq": 0,
            "ops": [
                {
                    "op_id": "op_agent",
                    "kind": "node.create",
                    "node": {
                        "id": "cnd_agent",
                        "kind": "agent",
                        "position": {"x": 0, "y": 0},
                        "data": {"label": "助手"},
                    },
                }
            ],
        },
        headers=auth_header(funded),
    )
    planned = client.post(
        f"/v1/canvas-projects/{canvas['id']}/agent-runs",
        json={"agent_node_id": "cnd_agent", "goal": "画一张雨夜街头的开场镜头"},
        headers=auth_header(funded),
    )
    assert planned.status_code == 202, planned.text
    run = next(
        json.loads(next(line[6:] for line in block.splitlines() if line.startswith("data: ")))
        for block in planned.text.split("\n\n")
        if "event: complete" in block.splitlines()
    )

    confirmed = client.post(
        f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded)
    )
    assert confirmed.status_code == 200, confirmed.text
    jobs = db.query(GenerationJob).all()
    images = [job for job in jobs if job.operation in ("text_to_image", "image_to_image")]
    assert images, [job.operation for job in jobs]
    assert all(
        not (job.request_json or {}).get("asset_kind")
        or (job.request_json["asset_kind"] == "general")
        for job in images
    )
