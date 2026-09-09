"""The canvas change stream: framing, resumption and access.

One connection per open canvas rather than one per generation in flight —
`sse_quota.MAX_CONCURRENT_STREAMS_PER_USER` is 8, so fanning out over the job
stream would let a four-task Agent run in two tabs eat a user's whole budget.

Unlike the job stream this has no terminal state: a canvas is never "finished",
so the generator would otherwise hold the connection until its own max duration.
The live tail is therefore monkeypatched to a finite generator, exactly as
`test_job_stream.py` does for the same reason.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1 import canvas as canvas_api
from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


@pytest.fixture(autouse=True)
def _finite_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ends the live tail immediately so the response completes.

    Autouse because *every* test here would otherwise block: the real
    subscriber yields an empty heartbeat slot once a second forever.
    """

    def empty_tail(_canvas_id: str) -> Iterator[dict[str, Any]]:
        return iter(())

    monkeypatch.setattr(canvas_api.publisher, "subscribe_canvas", empty_tail)


def _set_canvas_flag(session: Session, *, enabled: bool) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": enabled})
    config_service.set_value(session, "feature_flags", value, actor_user_id=None, note="test")


def _canvas(client: TestClient, user: User) -> dict:
    return client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(user)
    ).json()


def _note(op_id: str, node_id: str) -> dict:
    return {
        "op_id": op_id,
        "kind": "node.create",
        "node": {"id": node_id, "kind": "note", "position": {"x": 0, "y": 0}, "data": {}},
    }


def _apply(client: TestClient, user: User, canvas_id: str, ops: list[dict]) -> dict:
    return client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={"base_seq": 0, "ops": ops},
        headers=auth_header(user),
    ).json()


def _stream(client: TestClient, user: User, canvas_id: str, *, last_event_id: str | None = None):
    headers = auth_header(user)
    if last_event_id is not None:
        headers = {**headers, "Last-Event-ID": last_event_id}
    return client.get(f"/v1/canvas-projects/{canvas_id}/events", headers=headers)


def _frames(body: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Parses an SSE body into (event name, id, payload), ignoring heartbeats."""
    parsed: list[tuple[str, str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        name = next((line[7:] for line in lines if line.startswith("event: ")), "")
        event_id = next((line[4:] for line in lines if line.startswith("id: ")), "")
        data = next((line[6:] for line in lines if line.startswith("data: ")), "")
        if data:
            parsed.append((name, event_id, json.loads(data)))
    return parsed


def test_the_stream_replays_the_history_from_the_origin(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a"), _note("op_b", "cnd_b")])

    response = _stream(client, author, canvas["id"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _frames(response.text)
    created = [
        payload["entity_id"] for _, _, payload in frames if payload.get("action") == "created"
    ]
    assert created == ["cnd_a", "cnd_b"]

    # Change frames carry an id, which is what makes the stream resumable.
    ids = [event_id for name, event_id, _ in frames if name == ""]
    assert all(ids) and [int(i) for i in ids] == sorted(int(i) for i in ids)


def test_the_backfill_ends_with_an_explicit_synced_marker(
    client: TestClient, db: Session, author: User
) -> None:
    """A client has to be able to tell "caught up, now live" from "still
    replaying" — the two call for different UI, and applying live frames
    part-way through a replay can apply them out of order."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])

    frames = _frames(_stream(client, author, canvas["id"]).text)
    names = [name for name, _, _ in frames]
    assert names[-1] == "synced", f"expected the backfill to close with synced, got {names}"
    # No `id:` — it is a position the client already holds, not a change.
    synced_id = next(event_id for name, event_id, _ in frames if name == "synced")
    assert synced_id == ""


def test_a_reconnect_replays_only_what_came_after_the_cursor(
    client: TestClient, db: Session, author: User
) -> None:
    """The point of `Last-Event-ID`: a dropped connection costs a reconnect,
    not a re-read of the whole canvas."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    first = _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])
    _apply(client, author, canvas["id"], [_note("op_b", "cnd_b")])

    frames = _frames(
        _stream(client, author, canvas["id"], last_event_id=str(first["change_seq"])).text
    )
    replayed = [payload.get("entity_id") for _, _, payload in frames if payload.get("action")]
    assert "cnd_b" in replayed
    assert "cnd_a" not in replayed, "an already-seen change was replayed"


def test_a_cursor_at_the_head_replays_nothing_but_still_reports_synced(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    applied = _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])

    frames = _frames(
        _stream(client, author, canvas["id"], last_event_id=str(applied["change_seq"])).text
    )
    assert [name for name, _, _ in frames] == ["synced"]


def test_a_garbled_cursor_is_treated_as_the_origin(
    client: TestClient, db: Session, author: User
) -> None:
    """A malformed header is a client bug, and the safe reading is "start over"
    rather than a 400 that leaves the canvas with no live updates at all."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])

    frames = _frames(_stream(client, author, canvas["id"], last_event_id="not-a-number").text)
    assert any(payload.get("entity_id") == "cnd_a" for _, _, payload in frames)


def test_the_stream_releases_its_database_transaction_before_the_live_tail(
    client: TestClient, db: Session, author: User
) -> None:
    """A canvas is never "finished", so the stream runs to its own max duration.

    FastAPI tears a dependency down only after the response completes, so
    without an explicit release the request session would sit `idle in
    transaction` for that whole time — one pinned connection per open canvas,
    holding back DDL and vacuum. A job stream gets away with the same shape
    only because it ends when the job does.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])

    from app.db import get_engine

    def idle_in_transaction() -> int:
        with get_engine().connect() as probe:
            return (
                probe.scalar(
                    text(
                        "select count(*) from pg_stat_activity "
                        "where datname = current_database() "
                        "and pid <> pg_backend_pid() "
                        "and state = 'idle in transaction'"
                    )
                )
                or 0
            )

    before = idle_in_transaction()
    response = _stream(client, author, canvas["id"])
    assert response.status_code == 200
    # The backfill still arrived, so the release did not cost the read.
    assert any(payload.get("entity_id") == "cnd_a" for _, _, payload in _frames(response.text))
    assert idle_in_transaction() <= before


def test_the_stream_is_closed_to_someone_who_cannot_see_the_canvas(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    # 404 rather than 403, matching every other canvas route: the existence of
    # someone else's canvas is not confirmed.
    assert _stream(client, remixer, canvas["id"]).status_code == 404


def test_the_stream_is_gated_on_the_feature_flag(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _set_canvas_flag(db, enabled=False)
    db.commit()

    assert _stream(client, author, canvas["id"]).status_code == 404


def test_an_active_collaborator_may_watch_the_series_canvas(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """A co-creator arranges the shared canvas, so they must also see other
    people's changes land — otherwise their view silently diverges."""
    from app.models import Series, SeriesCollaborator
    from app.models.enums import SeriesCollaboratorStatus, SeriesKind

    _set_canvas_flag(db, enabled=True)
    series = Series(
        owner_user_id=author.id,
        title="共创短剧",
        kind=SeriesKind.DRAMA,
        target_platforms_json=["douyin"],
    )
    db.add(series)
    db.flush()
    db.add(
        SeriesCollaborator(
            series_id=series.id,
            user_id=remixer.id,
            invited_by_user_id=author.id,
            status=SeriesCollaboratorStatus.ACTIVE,
        )
    )
    db.flush()
    canvas = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()

    assert _stream(client, remixer, canvas["id"]).status_code == 200
