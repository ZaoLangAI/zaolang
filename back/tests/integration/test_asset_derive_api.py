"""P6: `…/entries/{entry_id}:adjust` and `:derive`, and the graph's pending
jobs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.models import Asset, CreationSkill, GenerationJob, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from app.workers import tasks
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


def _card_with_sheet(client: TestClient, db: Session, user: User) -> tuple[dict, str]:
    card = client.post("/v1/characters", json={"name": "林夏"}, headers=auth_header(user)).json()
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
    entry = client.post(
        f"/v1/characters/{card['id']}/looks/{card['looks'][0]['id']}/entries",
        json={"asset_id": asset.id, "entry_type": "character_sheet"},
        headers=auth_header(user),
    ).json()
    return card, entry["id"]


def test_an_adjust_dry_run_only_prices(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card_with_sheet(client, db, author)
    body = client.post(
        f"/v1/characters/{card['id']}/entries/{entry_id}:adjust",
        json={"instruction": "把外套换成红色"},
        headers=auth_header(author),
    ).json()
    assert body["credits"] > 0
    assert body["job_id"] is None and dispatched == []


def test_an_adjust_submits_one_job_and_replays(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    card, entry_id = _card_with_sheet(client, db, author)
    headers = {**auth_header(author), "Idempotency-Key": "adjust-1"}
    url = f"/v1/characters/{card['id']}/entries/{entry_id}:adjust"
    first = client.post(
        url, json={"instruction": "把外套换成红色", "dry_run": False}, headers=headers
    )
    assert first.status_code == 200, first.text
    job = db.get(GenerationJob, first.json()["job_id"])
    assert job is not None
    assert job.request_json["asset_edit"] is True
    assert job.request_json["source_entry_id"] == entry_id
    # Reference 1 is the source image.
    sheet = av.find_entry(db.get(CreationSkill, card["id"]), entry_id)
    assert job.request_json["reference_asset_ids"][0] == sheet.asset_id
    assert dispatched == [job.id]

    again = client.post(
        url, json={"instruction": "把外套换成红色", "dry_run": False}, headers=headers
    )
    assert again.json()["job_id"] == job.id and again.json()["replayed"] is True
    assert dispatched == [job.id]


def test_a_derive_into_a_new_look_creates_it_with_an_edge(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    card, entry_id = _card_with_sheet(client, db, author)
    headers = {**auth_header(author), "Idempotency-Key": "derive-1"}
    url = f"/v1/characters/{card['id']}/entries/{entry_id}:derive"
    payload = {
        "output": "character_sheet",
        "new_variant": {"name": "老年", "presets": {"age_stage": "elderly"}},
    }
    preview = client.post(url, json=payload, headers=headers).json()
    assert preview["relations"] == ["age"]
    assert preview["variant_id"] is None

    submitted = client.post(url, json={**payload, "dry_run": False}, headers=headers)
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["job_id"] and body["variant_id"] and body["edge_id"]

    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=auth_header(author)).json()
    assert [v["name"] for v in graph["variants"]] == ["默认造型", "老年"]
    (edge,) = graph["edges"]
    assert edge["level"] == "variant" and edge["origin"] == "auto"
    assert edge["target_id"] == body["variant_id"]
    (pending,) = graph["pending"]
    assert pending["job_id"] == body["job_id"]
    assert pending["target_variant_id"] == body["variant_id"]
    assert pending["mode"] == "derive"

    # A retry must not try to create the look again.
    again = client.post(url, json={**payload, "dry_run": False}, headers=headers).json()
    assert again["job_id"] == body["job_id"] and again["replayed"] is True


def test_insufficient_credits_create_nothing(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    card, entry_id = _card_with_sheet(client, db, author)
    response = client.post(
        f"/v1/characters/{card['id']}/entries/{entry_id}:derive",
        json={"output": "character_sheet", "new_variant": {"name": "老年"}, "dry_run": False},
        headers=auth_header(author),
    )
    assert response.status_code == 402
    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=auth_header(author)).json()
    assert len(graph["variants"]) == 1 and dispatched == []


def test_someone_elses_image_is_a_404(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    card, entry_id = _card_with_sheet(client, db, author)
    mine = client.post("/v1/characters", json={"name": "周岩"}, headers=auth_header(remixer)).json()
    response = client.post(
        f"/v1/characters/{mine['id']}/entries/{entry_id}:adjust",
        json={"instruction": "x"},
        headers=auth_header(remixer),
    )
    assert response.status_code == 404
    response = client.post(
        f"/v1/characters/{card['id']}/entries/{entry_id}:adjust",
        json={"instruction": "x"},
        headers=auth_header(remixer),
    )
    assert response.status_code == 404


# ---- consistency scoring of derived images (P3-3) -------------------------


def _stored_sheet_card(client: TestClient, db: Session, user: User) -> tuple[dict, str]:
    """`_card_with_sheet`, with real image bytes so the judge can read it."""
    import io

    from PIL import Image

    from app.storage import s3

    card, entry_id = _card_with_sheet(client, db, user)
    entry = av.find_entry(db.get(CreationSkill, card["id"]), entry_id)
    asset = db.get(Asset, entry.asset_id)
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 80, 40)).save(buffer, format="PNG")
    s3.put_object(asset.object_key, buffer.getvalue(), content_type="image/png")
    return card, entry_id


def test_adjusted_derived_and_orbited_images_are_all_scored(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    from sqlalchemy import select

    from app.domain.workflow_templates import service as workflow_templates_service
    from app.models import AgentRun, SkillAssetEntry
    from app.platform_config import service as config_service
    from app.platform_config.schemas import DEFAULT_CONFIGS
    from app.workers import pipeline

    workflow_templates_service.ensure_default_templates(db)
    credits_service.grant(db, author.id, 50_000, idempotency_key=new_id("grant"))
    config_service.set_value(
        db,
        "asset_consistency",
        {**DEFAULT_CONFIGS["asset_consistency"], "mode": "shadow"},
        actor_user_id=None,
        note="test",
    )
    card, entry_id = _stored_sheet_card(client, db, author)
    base = f"/v1/characters/{card['id']}/entries/{entry_id}"
    requests = [
        (":adjust", {"instruction": "把外套换成红色", "dry_run": False}),
        (
            ":derive",
            {
                "output": "character_sheet",
                "new_variant": {"name": "老年", "presets": {"age_stage": "elderly"}},
                "dry_run": False,
            },
        ),
        (":orbit", {"poses": [{"azimuth": 90}, {"azimuth": 180}], "dry_run": False}),
    ]
    for action, body in requests:
        response = client.post(
            f"{base}{action}",
            json=body,
            headers={**auth_header(author), "Idempotency-Key": f"score{action}"},
        )
        assert response.status_code == 200, response.text
    assert len(dispatched) == 3

    for job_id in dispatched:
        assert pipeline.run_generation_pipeline(db, job_id).status == "succeeded"

    entries = list(
        db.scalars(select(SkillAssetEntry).where(SkillAssetEntry.source_job_id.in_(dispatched)))
    )
    assert entries
    assert all(e.consistency_json and e.consistency_json["status"] == "scored" for e in entries)
    assert {e.consistency_json["anchor_entry_id"] for e in entries} == {entry_id}
    by_job = {
        run.job_id: run.input_json["user_prompt"]
        for run in db.scalars(select(AgentRun).where(AgentRun.prompt_slot == "consistency"))
    }
    # The derive goes into a new look: the outfit is not compared.
    assert "outfit" not in by_job[dispatched[1]].split("维度键：")[1].splitlines()[0]
    assert "outfit" in by_job[dispatched[0]].split("维度键：")[1].splitlines()[0]
