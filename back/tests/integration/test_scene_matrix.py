"""P2-5: a scene card's lighting × weather × state × period matrix, planned,
priced and submitted as one image job per new cell."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.domain.errors import ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.scenes import matrix
from app.domain.scenes import service as scenes_service
from app.models import Asset, GenerationJob, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Operation, Visibility
from app.workers import tasks
from tests.conftest import auth_header, make_user

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="f" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    return asset


def _scene(db: Session, author: User):
    return scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description="老式客厅，木地板", reference_asset_ids=[]
    )


def _url(scene_id: str) -> str:
    return f"/v1/scenes/{scene_id}/variants:matrix"


def test_cells_are_the_cartesian_product_with_what_the_card_holds(
    db: Session, author: User
) -> None:
    scene = _scene(db, author)
    dusk_rain = av.create_variant(
        db, scene.skill, name="黄昏·雨", presets={"lighting": "dusk", "weather": "rain"}
    )
    plate = _asset(db, author)
    av.add_entry(db, scene.skill, dusk_rain, asset_id=plate.id, entry_type="master")

    cells = matrix.plan(
        scene.skill, {"lighting": ["day", "dusk"], "weather": ["clear", "rain"], "state": []}
    )

    assert [(c.presets, c.status) for c in cells] == [
        ({"lighting": "day", "weather": "clear"}, "new"),
        ({"lighting": "day", "weather": "rain"}, "new"),
        ({"lighting": "dusk", "weather": "clear"}, "new"),
        ({"lighting": "dusk", "weather": "rain"}, "exists"),
    ]
    assert cells[3].variant_id == dusk_rain.id


def test_the_matrix_is_bounded_per_request(db: Session, author: User) -> None:
    scene = _scene(db, author)
    with pytest.raises(ValidationFailed):
        matrix.plan(
            scene.skill,
            {
                "lighting": ["day", "dusk", "dawn", "candle"],
                "weather": ["clear", "rain", "snow", "fog"],
            },
        )
    with pytest.raises(ValidationFailed):
        matrix.plan(scene.skill, {})


def test_a_dry_run_prices_only_the_new_cells(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    scene = _scene(db, author)
    response = client.post(
        _url(scene.id),
        json={"axes": {"lighting": ["day", "dusk", "night_interior"]}},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    unit = jobs_service.quote_for(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier="standard"
    ).credits
    assert body["unit_credits"] == unit
    assert body["total_credits"] == unit * 3
    assert body["sufficient"] is True
    assert body["submitted"] == 0
    assert dispatched == []


def test_a_submit_queues_one_scene_job_per_new_cell_and_replays_on_retry(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    scene = _scene(db, author)
    payload = {"axes": {"lighting": ["day", "dusk"], "state": ["damage_light"]}, "dry_run": False}
    headers = {**auth_header(author), "Idempotency-Key": "matrix-1"}

    first = client.post(_url(scene.id), json=payload, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["submitted"] == 2
    job_ids = [cell["job_id"] for cell in body["cells"]]
    assert all(job_ids) and len(dispatched) == 2

    jobs = [db.get(GenerationJob, job_id) for job_id in job_ids]
    params = [job.request_json for job in jobs]  # type: ignore[union-attr]
    assert {(p["scene_lighting"], p["scene_state"]) for p in params} == {
        ("day", "damage_light"),
        ("dusk", "damage_light"),
    }
    assert all(p["target_scene_id"] == scene.id and p["asset_kind"] == "scene" for p in params)
    assert all(p["prompt"] == "客厅。老式客厅，木地板" for p in params)

    again = client.post(_url(scene.id), json=payload, headers=headers)
    assert [cell["job_id"] for cell in again.json()["cells"]] == job_ids
    assert len(dispatched) == 2
    total_jobs = db.scalars(select(GenerationJob).where(GenerationJob.user_id == author.id)).all()
    assert len(total_jobs) == 2


def test_a_submit_that_does_not_fit_the_balance_queues_nothing(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    scene = _scene(db, author)
    response = client.post(
        _url(scene.id),
        json={"axes": {"lighting": ["day", "dusk"]}, "dry_run": False},
        headers=auth_header(author),
    )
    assert response.status_code == 402
    assert dispatched == []


def test_someone_elses_scene_is_a_404(client: TestClient, db: Session, author: User) -> None:
    scene = _scene(db, author)
    stranger = make_user(db, email="matrix@example.com", handle="matrixer", display_name="路人")
    response = client.post(
        _url(scene.id), json={"axes": {"lighting": ["day"]}}, headers=auth_header(stranger)
    )
    assert response.status_code == 404


def test_scene_cards_take_more_than_twelve_variants(db: Session, author: User) -> None:
    scene = _scene(db, author)
    combos = [
        {"lighting": lighting, "weather": weather}
        for lighting in ("day", "dusk", "night_interior")
        for weather in ("clear", "rain", "snow", "fog", "sandstorm")
    ][:14]
    for index, presets in enumerate(combos):
        av.create_variant(db, scene.skill, name=f"变体{index}", presets=presets)
    assert len(av.variants(scene.skill)) == 15
