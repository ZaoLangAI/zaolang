"""Edit-plan lifecycle, flag-order regression, and concurrency races.

Covers gaps the drama-editor test suite was missing: the AI plan flow was
completely untested, the AI-flag-checked-after-LLM-call bug had no regression
test, and neither concurrent revision writes nor concurrent lease acquires
were exercised against the real database.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agents import editor_planner
from app.agents.base import AgentOutcome
from app.domain.editor import leases as lease_service
from app.domain.editor import service as editor_service
from app.domain.errors import LeaseHeld, OperationTerminal, RevisionConflict
from app.models import Asset, EditorLease, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, patch_app_db_session_scope


def _enable_editor(session: Session, admin: User, *, ai: bool = True) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update(
        {
            "drama_studio_enabled": True,
            "web_editor_enabled": True,
            "variant_export_enabled": True,
            "editor_ai_enabled": ai,
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


def _open_cut(client: TestClient, author: User, asset: Asset) -> dict:
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "测试短剧", "target_platforms": ["manual_download"]},
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


def _poison_pill(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails the test if the LLM planner is invoked at all."""

    def _boom(*_args: object, **_kwargs: object) -> AgentOutcome:
        raise AssertionError("plan_timeline must not run when editor_ai_enabled is off")

    monkeypatch.setattr(editor_planner, "plan_timeline", _boom)
    monkeypatch.setattr(editor_planner, "stream_plan_timeline", _boom)


def _fake_plan_outcome(commands: list[dict[str, object]]) -> AgentOutcome:
    return AgentOutcome(
        data={"summary": "stub plan", "commands": commands, "warnings": []},
        raw_text="",
        degraded=False,
        model="stub:test",
        agent_run_id=None,  # type: ignore[arg-type]
    )


def _fake_stream_plan(commands: list[dict[str, object]]):
    outcome = _fake_plan_outcome(commands)

    def _stream(*_args: object, **_kwargs: object):
        return iter(()), lambda session=None: outcome

    return _stream


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        event_line = next((line for line in lines if line.startswith("event: ")), None)
        data_line = next((line for line in lines if line.startswith("data: ")), None)
        if event_line is None or data_line is None:
            continue
        events.append((event_line[len("event: ") :], json.loads(data_line[len("data: ") :])))
    return events


def _plan_from_sse(response) -> dict[str, Any]:
    return next(data for kind, data in _parse_sse(response.text) if kind == "complete")


def _patch_stream_session(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    # Imported inside the route: `from app.db import session_scope`.
    patch_app_db_session_scope(monkeypatch, db)


# --- flag-order regression -------------------------------------------------


def test_edit_plan_rest_checks_flag_before_calling_the_llm(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_editor(db, admin, ai=False)
    _poison_pill(monkeypatch)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    response = client.post(
        f"/v1/episode-cuts/{opened['cut']['id']}/edit-plans",
        headers=auth_header(author),
        json={"goal": "去掉多余的沉默"},
    )
    assert response.status_code == 404


def test_edit_plan_mcp_checks_flag_before_calling_the_llm(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_editor(db, admin, ai=False)
    _poison_pill(monkeypatch)
    asset = _video_asset(db, author)
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "MCP 计划剧", "target_platforms": ["manual_download"]},
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
    minted = client.post(
        "/v1/mcp/tokens",
        headers=auth_header(author),
        json={
            "series_id": series["id"],
            "client_id": "cursor",
            "scopes": ["drama:read", "editor:read", "editor:write"],
        },
    )
    assert minted.status_code == 201, minted.text
    call = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {minted.json()['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "editor.generate_edit_plan",
                "arguments": {"project_id": series["id"], "cut_id": cut["id"], "goal": "去掉沉默"},
            },
        },
    )
    # The poison pill raises a bare AssertionError, which is not a DomainError
    # and so would surface as an unhandled 500 if plan_timeline ran. A clean
    # 404/NOT_FOUND proves the flag check ran first and the LLM was never
    # invoked.
    assert call.status_code == 404, call.text
    assert call.json()["error"]["data"]["message"] == "该功能暂未开放。"


# --- edit-plan lifecycle -----------------------------------------------------


def test_edit_plan_create_apply_produces_a_new_revision(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_editor(db, admin)
    _patch_stream_session(monkeypatch, db)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    cut_id = opened["cut"]["id"]
    head_id = opened["cut"]["head_revision_id"]

    monkeypatch.setattr(
        editor_planner,
        "stream_plan_timeline",
        _fake_stream_plan(
            [
                {
                    "type": "insert_caption",
                    "track_id": "trk_caption",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "text": "AI 生成的字幕",
                }
            ]
        ),
    )

    created = client.post(
        f"/v1/episode-cuts/{cut_id}/edit-plans",
        headers=auth_header(author),
        json={"goal": "加一句开场字幕"},
    )
    assert created.status_code == 202, created.text
    plan = _plan_from_sse(created)
    assert plan["status"] == "validated"
    assert len(plan["commands"]) == 1

    applied = client.post(
        f"/v1/edit-plans/{plan['id']}/apply",
        headers=auth_header(author),
        json={"lease_id": opened["lease"]["id"], "lease_token": opened["lease"]["token"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["id"] != head_id

    current = client.get(f"/v1/episode-cuts/{cut_id}", headers=auth_header(author))
    assert current.json()["head_revision_id"] == applied.json()["id"]


def test_edit_plan_apply_rejects_a_stale_base_revision(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_editor(db, admin)
    _patch_stream_session(monkeypatch, db)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    cut_id = opened["cut"]["id"]
    lease = opened["lease"]

    monkeypatch.setattr(
        editor_planner,
        "stream_plan_timeline",
        _fake_stream_plan([{"type": "set_canvas", "width": 1080, "height": 1920}]),
    )
    plan = _plan_from_sse(
        client.post(
            f"/v1/episode-cuts/{cut_id}/edit-plans",
            headers=auth_header(author),
            json={"goal": "调整画幅"},
        )
    )

    # A manual edit lands first, moving the head out from under the plan.
    manual = client.post(
        f"/v1/episode-cuts/{cut_id}/revisions",
        headers=auth_header(author),
        json={
            "schema_version": 1,
            "batch_id": "bat_manual",
            "expected_revision_id": opened["cut"]["head_revision_id"],
            "lease_id": lease["id"],
            "lease_token": lease["token"],
            "commands": [
                {
                    "type": "insert_caption",
                    "track_id": "trk_caption",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "text": "手动字幕",
                }
            ],
        },
    )
    assert manual.status_code == 201

    stale_apply = client.post(
        f"/v1/edit-plans/{plan['id']}/apply",
        headers=auth_header(author),
        json={"lease_id": lease["id"], "lease_token": lease["token"]},
    )
    assert stale_apply.status_code == 409
    assert stale_apply.json()["error"]["code"] == "REVISION_CONFLICT"


def test_edit_plan_reject_marks_it_terminal(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_editor(db, admin)
    _patch_stream_session(monkeypatch, db)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    monkeypatch.setattr(
        editor_planner,
        "stream_plan_timeline",
        _fake_stream_plan([{"type": "set_canvas", "width": 1080, "height": 1920}]),
    )
    plan = _plan_from_sse(
        client.post(
            f"/v1/episode-cuts/{opened['cut']['id']}/edit-plans",
            headers=auth_header(author),
            json={"goal": "不想要这个方案"},
        )
    )
    rejected = client.post(f"/v1/edit-plans/{plan['id']}/reject", headers=auth_header(author))
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


# --- terminal states cannot be reopened by a late heartbeat -----------------


def test_lease_heartbeat_cannot_reopen_an_expired_lease(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    lease_row = db.get(EditorLease, opened["lease"]["id"])
    assert lease_row is not None
    lease_row.expires_at = lease_row.expires_at.replace(year=2000)
    db.flush()
    with pytest.raises(LeaseHeld):
        lease_service.heartbeat(db, lease=lease_row)


def test_export_heartbeat_cannot_reopen_a_terminal_export(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    from app.domain.editor import exports as export_service
    from app.models import DeliveryVariant, EditorExport
    from app.models.enums import DeliveryVariantStatus, EditorExportStatus

    _enable_editor(db, admin)
    asset = _video_asset(db, author)
    opened = _open_cut(client, author, asset)
    variant = DeliveryVariant(
        cut_revision_id=opened["cut"]["head_revision_id"],
        profile_key="douyin_9_16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        spec_json={},
        spec_hash="d" * 64,
        status=DeliveryVariantStatus.READY,
    )
    db.add(variant)
    db.flush()
    export = EditorExport(
        variant_id=variant.id,
        status=EditorExportStatus.SUCCEEDED,
        operation_key="op_terminal",
        attempt=1,
        progress=100,
    )
    db.add(export)
    db.flush()
    with pytest.raises(OperationTerminal):
        export_service.heartbeat(
            db, user_id=author.id, export_id=export.id, progress=50, stage="encoding"
        )


# --- concurrency races, exercised against real committed transactions ------


def _second_session() -> Session:
    from app.db import get_engine

    return Session(bind=get_engine(), expire_on_commit=False)


def test_concurrent_apply_commands_yields_one_winner_and_one_conflict(
    committed_db: Session,
) -> None:
    # `admin`/`author` are seeded through the rolled-back `db` fixture; a
    # `committed_db` test needs its own users so every row is visible across
    # the separate connections the race below opens.
    from tests.conftest import make_user

    author = make_user(committed_db, email="racer-author@example.com", handle="raceauthor")
    admin = make_user(
        committed_db,
        email="racer-admin@example.com",
        handle="raceadmin",
        roles=["user", "admin"],
    )
    _enable_editor(committed_db, admin)
    asset = _video_asset(committed_db, author)
    from app.domain.editor import service as svc

    series = svc.create_drama_series(
        committed_db, user_id=author.id, title="并发剧", target_platforms=["manual_download"]
    )
    episode = svc.create_episode(committed_db, user_id=author.id, series_id=series.id, title="一")
    cut, head = svc.create_cut_from_asset(
        committed_db, user_id=author.id, episode_id=episode.id, asset_id=asset.id, name="主剪辑"
    )
    lease, token = lease_service.acquire(
        committed_db, cut=cut, user_id=author.id, browser_instance_id="racer"
    )
    committed_db.commit()

    results: list[object] = []
    barrier = threading.Barrier(2)

    def _race(offset_seconds: int) -> None:
        session = _second_session()
        try:
            barrier.wait(timeout=5)
            revision = editor_service.apply_commands(
                session,
                user_id=author.id,
                cut_id=cut.id,
                lease_id=lease.id,
                lease_token=token,
                payload={
                    "schema_version": 1,
                    "batch_id": new_id("bat"),
                    "expected_revision_id": head.id,
                    "commands": [
                        {
                            "type": "insert_caption",
                            "track_id": "trk_caption",
                            "at_ticks": offset_seconds * 120_000,
                            "duration_ticks": 120_000,
                            "text": f"racer-{offset_seconds}",
                        }
                    ],
                },
            )
            session.commit()
            results.append(revision.id)
        except RevisionConflict:
            session.rollback()
            results.append("conflict")
        except Exception as exc:  # pragma: no cover - failure diagnostic
            session.rollback()
            results.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_race, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 2
    conflicts = [item for item in results if item == "conflict"]
    winners = [item for item in results if isinstance(item, str) and item != "conflict"]
    errors = [item for item in results if isinstance(item, Exception)]
    assert not errors, (
        f"race produced an unexpected exception instead of a domain conflict: {errors}"
    )
    assert len(winners) == 1
    assert len(conflicts) == 1


def test_concurrent_lease_acquire_yields_one_winner(committed_db: Session) -> None:
    from tests.conftest import make_user

    admin = make_user(
        committed_db,
        email="lease-race-admin@example.com",
        handle="leaseraceadmin",
        roles=["user", "admin"],
    )
    _enable_editor(committed_db, admin)
    owner = make_user(committed_db, email="racer-owner@example.com", handle="raceowner")
    asset = _video_asset(committed_db, owner)
    from app.domain.editor import service as svc

    series = svc.create_drama_series(
        committed_db, user_id=owner.id, title="租约赛跑", target_platforms=["manual_download"]
    )
    episode = svc.create_episode(committed_db, user_id=owner.id, series_id=series.id, title="一")
    cut, _head = svc.create_cut_from_asset(
        committed_db, user_id=owner.id, episode_id=episode.id, asset_id=asset.id, name="主剪辑"
    )
    committed_db.commit()

    outcomes: list[object] = []
    barrier = threading.Barrier(2)

    def _race(instance_id: str) -> None:
        session = _second_session()
        try:
            fresh_cut = session.get(type(cut), cut.id)
            barrier.wait(timeout=5)
            _lease, _token = lease_service.acquire(
                session, cut=fresh_cut, user_id=owner.id, browser_instance_id=instance_id
            )
            session.commit()
            outcomes.append("acquired")
        except LeaseHeld:
            session.rollback()
            outcomes.append("held")
        except Exception as exc:  # pragma: no cover - failure diagnostic
            session.rollback()
            outcomes.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_race, args=(f"racer-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(outcomes) == 2
    errors = [item for item in outcomes if isinstance(item, Exception)]
    assert not errors, f"lease race produced an unexpected exception: {errors}"
    assert outcomes.count("acquired") == 1
    assert outcomes.count("held") == 1
