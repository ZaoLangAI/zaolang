"""P2-4: `POST /v1/characters/{id}/looks/{look_id}:fill`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import Operation
from app.workers import tasks
from tests.conftest import auth_header, make_user

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


def _character(client: TestClient, author: User) -> dict:
    response = client.post("/v1/characters", json={"name": "林夏"}, headers=auth_header(author))
    assert response.status_code == 201
    return response.json()


def _url(character: dict) -> str:
    return f"/v1/characters/{character['id']}/looks/{character['looks'][0]['id']}:fill"


def test_a_dry_run_reports_gaps_and_prices_every_wave(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    character = _character(client, author)

    body = client.post(_url(character), json={}, headers=auth_header(author)).json()

    assert body["gaps"] == dict.fromkeys(
        ["portrait", "front", "side", "back", "expressions"], "missing"
    )
    assert [line["slots"] for line in body["lines"]] == [
        ["portrait"],
        ["front", "side", "back"],
        ["expressions"],
    ]
    unit = jobs_service.quote_for(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier="standard"
    ).credits
    assert body["total_credits"] == sum(line["credits"] for line in body["lines"])
    assert (
        body["lines"][1]["credits"]
        == jobs_service.quote_for(
            db, operation=Operation.TEXT_TO_IMAGE, quality_tier="standard", output_count=3
        ).credits
    )
    assert body["lines"][0]["credits"] == unit
    assert body["submitted_job_id"] is None and dispatched == []


def test_a_submit_queues_only_the_next_wave_and_replays_on_retry(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    character = _character(client, author)
    headers = {**auth_header(author), "Idempotency-Key": "fill-1"}

    first = client.post(_url(character), json={"dry_run": False}, headers=headers).json()
    assert first["submitted_slots"] == ["portrait"]
    job = db.get(GenerationJob, first["submitted_job_id"])
    assert job is not None and job.request_json["character_portrait"] is True
    assert len(dispatched) == 1

    again = client.post(_url(character), json={"dry_run": False}, headers=headers).json()
    assert again["submitted_job_id"] == first["submitted_job_id"]
    assert len(dispatched) == 1


def test_a_submit_that_does_not_fit_queues_nothing(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    character = _character(client, author)
    response = client.post(_url(character), json={"dry_run": False}, headers=auth_header(author))
    assert response.status_code == 402
    assert dispatched == []


def test_someone_elses_look_is_a_404(client: TestClient, db: Session, author: User) -> None:
    character = _character(client, author)
    stranger = make_user(db, email="filler@example.com", handle="filler", display_name="路人")
    assert client.post(_url(character), json={}, headers=auth_header(stranger)).status_code == 404
    other = f"/v1/characters/{character['id']}/looks/skv_missing:fill"
    assert client.post(other, json={}, headers=auth_header(author)).status_code == 404


def test_dry_runs_do_not_spend_the_submit_budget(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    """The dialog quotes on open and between waves; only a submitted job
    counts against `generation_submit` (12 a minute)."""
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    character = _character(client, author)

    for _ in range(12):
        quote = client.post(_url(character), json={}, headers=auth_header(author))
        assert quote.status_code == 200, quote.text
    submit = client.post(_url(character), json={"dry_run": False}, headers=auth_header(author))

    assert submit.status_code == 200, submit.text
    assert len(dispatched) == 1
