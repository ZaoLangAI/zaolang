"""SSE progress stream: framing, resumption and ownership."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import Operation, QualityTier
from app.workers import pipeline
from tests.conftest import auth_header


@pytest.fixture
def finished_job(db: Session, author: User) -> GenerationJob:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    return result.job


def _events(body: str) -> list[tuple[str, str]]:
    """Parses an SSE body into (id, data) pairs, ignoring heartbeats."""
    frames = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        event_id = next((line[4:] for line in lines if line.startswith("id: ")), "")
        data = next((line[6:] for line in lines if line.startswith("data: ")), "")
        if data:
            frames.append((event_id, data))
    return frames


def test_the_stream_replays_the_whole_history_for_a_fresh_client(
    client: TestClient, author: User, finished_job: GenerationJob
) -> None:
    response = client.get(
        f"/v1/generation-jobs/{finished_job.id}/events", headers=auth_header(author)
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _events(response.text)
    assert frames
    assert [int(i) for i, _ in frames] == sorted(int(i) for i, _ in frames)


def test_reconnecting_with_a_last_event_id_skips_what_was_already_seen(
    client: TestClient, author: User, finished_job: GenerationJob
) -> None:
    """Without this a dropped connection would either lose progress steps or
    replay them as duplicates."""
    headers = auth_header(author)
    full = _events(
        client.get(f"/v1/generation-jobs/{finished_job.id}/events", headers=headers).text
    )
    assert len(full) > 2

    resume_from = full[1][0]
    resumed = _events(
        client.get(
            f"/v1/generation-jobs/{finished_job.id}/events",
            headers={**headers, "Last-Event-ID": resume_from},
        ).text
    )
    assert [i for i, _ in resumed] == [i for i, _ in full if int(i) > int(resume_from)]


def test_a_malformed_last_event_id_replays_from_the_start(
    client: TestClient, author: User, finished_job: GenerationJob
) -> None:
    """A garbled header must not silently drop the user's progress history."""
    headers = {**auth_header(author), "Last-Event-ID": "not-a-number"}
    frames = _events(
        client.get(f"/v1/generation-jobs/{finished_job.id}/events", headers=headers).text
    )
    assert frames and frames[0][0] == "1"


def test_another_user_cannot_watch_someone_elses_job(
    client: TestClient, remixer: User, finished_job: GenerationJob
) -> None:
    response = client.get(
        f"/v1/generation-jobs/{finished_job.id}/events", headers=auth_header(remixer)
    )
    assert response.status_code == 404


def test_an_anonymous_caller_cannot_watch_a_job(
    client: TestClient, finished_job: GenerationJob
) -> None:
    assert client.get(f"/v1/generation-jobs/{finished_job.id}/events").status_code == 401
