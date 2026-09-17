"""Script → rough cut: `POST /v1/episode-cuts:assemble` lays the episode's
generated breakpoint videos, dubbed lines and dialogue captions onto its
粗剪 cut, in the script's own breakpoint order."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, CutRevision, Draft, DramaEpisode, User
from app.models.base import new_id
from app.models.editor import EpisodeCut
from app.models.enums import (
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user
from tests.factories import make_job

SECOND = 120_000

# 日·客厅 has one closed segment (#0, blocks 0-2) and an unclosed tail that
# gets the virtual closer #1 (blocks 4-5); 夜·街道 has one segment (#0).
SCRIPT: dict[str, Any] = {
    "title": "雨夜",
    "scenes": [
        {
            "heading": "日·客厅",
            "blocks": [
                {"type": "action", "text": "她推门进来", "character": None},
                {"type": "dialogue", "text": "你还在等我？", "character": "林夏"},
                {"type": "dialogue", "text": "一直在。", "character": "周屿"},
                {"type": "breakpoint", "text": "切", "character": None},
                {"type": "action", "text": "窗外下雨", "character": None},
                {"type": "dialogue", "text": "走吧。", "character": "林夏"},
            ],
        },
        {
            "heading": "夜·街道",
            "blocks": [
                {"type": "action", "text": "两人并肩走远", "character": None},
                {"type": "breakpoint", "text": "切", "character": None},
            ],
        },
    ],
}


def _enable_editor(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"drama_studio_enabled": True, "web_editor_enabled": True})
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def _asset(session: Session, owner: User, *, media_type: str, duration_ms: int | None) -> Asset:
    video = media_type == MediaType.VIDEO
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.{'mp4' if video else 'mp3'}",
        media_type=media_type,
        mime_type="video/mp4" if video else "audio/mpeg",
        size_bytes=2048,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1080 if video else None,
        height=1920 if video else None,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _episode(client: TestClient, db: Session, author: User) -> str:
    series = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "雨夜", "target_platforms": ["manual_download"]},
    )
    assert series.status_code == 201, series.text
    episode = client.post(
        f"/v1/drama-series/{series.json()['id']}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    )
    assert episode.status_code == 201, episode.text
    row = db.get(DramaEpisode, episode.json()["id"])
    assert row is not None
    row.script_json = SCRIPT
    db.flush()
    return row.id


def _bind(
    db: Session,
    owner: User,
    episode_id: str,
    key: str,
    *,
    operation: str,
    asset: Asset | None = None,
) -> Draft:
    draft = Draft(
        user_id=owner.id,
        params_json={
            "link_episode_id": episode_id,
            "link_breakpoint_key": key,
            "operation": operation,
        },
        output_asset_id=asset.id if asset else None,
    )
    db.add(draft)
    db.flush()
    return draft


def _assemble(client: TestClient, user: User, episode_id: str, **extra: Any) -> httpx.Response:
    return client.post(
        "/v1/episode-cuts:assemble",
        headers=auth_header(user),
        json={"episode_id": episode_id, **extra},
    )


def _placed(db: Session, cut_id: str) -> dict[str, list[tuple[Any, int, int]]]:
    """Per track: `(asset_id or caption text, start, duration)` in time order."""
    cut = db.get(EpisodeCut, cut_id)
    assert cut is not None
    db.refresh(cut)
    revision = db.get(CutRevision, cut.head_revision_id)
    assert revision is not None
    placed: dict[str, list[tuple[Any, int, int]]] = {}
    for track in revision.document_json["tracks"]:
        elements = sorted(track["elements"], key=lambda element: element["start_ticks"])
        placed[track["id"]] = [
            (
                element["asset_id"] or element["text"],
                element["start_ticks"],
                element["duration_ticks"],
            )
            for element in elements
        ]
    return placed


def test_assemble_lays_videos_voice_and_captions_in_script_order(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    living = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=10_000)
    street = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=6_000)
    first_line = _asset(db, author, media_type=MediaType.AUDIO, duration_ms=2_000)
    second_line = _asset(db, author, media_type=MediaType.AUDIO, duration_ms=3_000)
    # Bound out of order on purpose: the script, not draft order, decides.
    _bind(db, author, episode_id, "夜·街道#0", operation=Operation.TEXT_TO_VIDEO, asset=street)
    _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO, asset=living)
    _bind(
        db, author, episode_id, "日·客厅#L1", operation=Operation.AUDIO_GENERATION, asset=first_line
    )
    _bind(
        db,
        author,
        episode_id,
        "日·客厅#L2",
        operation=Operation.AUDIO_GENERATION,
        asset=second_line,
    )

    response = _assemble(client, author, episode_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cut"]["name"] == "粗剪"
    assert body["cut"]["kind"] == "full"
    # The closer segment has no video yet; its line "走吧。" is left out too.
    assert body["skipped"] == [{"key": "日·客厅#1", "reason": "no_output"}]
    placed = _placed(db, body["cut"]["id"])
    assert placed["trk_video"] == [
        (living.id, 0, 10 * SECOND),
        (street.id, 10 * SECOND, 6 * SECOND),
    ]
    assert placed["trk_audio"] == [
        (first_line.id, 0, 2 * SECOND),
        (second_line.id, 2 * SECOND, 3 * SECOND),
    ]
    assert placed["trk_caption"] == [
        ("你还在等我？", 0, 2 * SECOND),
        ("一直在。", 2 * SECOND, 3 * SECOND),
    ]


def test_a_repeat_assemble_reuses_the_rough_cut_and_its_revision(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    video = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=5_000)
    _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO, asset=video)

    first = _assemble(client, author, episode_id)
    second = _assemble(client, author, episode_id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["cut"]["id"] == first.json()["cut"]["id"]
    assert second.json()["cut"]["head_revision_id"] == first.json()["cut"]["head_revision_id"]
    cuts = db.scalars(select(EpisodeCut).where(EpisodeCut.episode_id == episode_id)).all()
    assert [cut.name for cut in cuts] == ["粗剪"]


def test_assemble_falls_back_to_the_latest_visible_job_and_skips_unknown_lengths(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    living_draft = _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO)
    visible = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=8_000)
    hidden = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=9_000)
    now = dt.datetime.now(dt.UTC)
    for asset, finished_at, hidden_at in (
        (visible, now - dt.timedelta(minutes=5), None),
        # Newer, but the author hid it from the draft's history.
        (hidden, now, now),
    ):
        job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO)
        job.draft_id = living_draft.id
        job.output_asset_id = asset.id
        job.finished_at = finished_at
        job.draft_history_hidden_at = hidden_at
    no_length = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=None)
    _bind(db, author, episode_id, "夜·街道#0", operation=Operation.IMAGE_TO_VIDEO, asset=no_length)
    voice = _asset(db, author, media_type=MediaType.AUDIO, duration_ms=2_000)
    _bind(db, author, episode_id, "日·客厅#L1", operation=Operation.AUDIO_GENERATION, asset=voice)
    db.flush()

    response = _assemble(client, author, episode_id, include_audio=False)

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == [
        {"key": "日·客厅#1", "reason": "no_output"},
        {"key": "夜·街道#0", "reason": "unknown_duration"},
    ]
    placed = _placed(db, response.json()["cut"]["id"])
    assert placed["trk_video"] == [(visible.id, 0, 8 * SECOND)]
    assert placed["trk_audio"] == []
    # No voice clip: captions get an estimated reading time (≥1.5s each).
    assert placed["trk_caption"] == [
        ("你还在等我？", 0, SECOND * 3 // 2),
        ("一直在。", SECOND * 3 // 2, SECOND * 3 // 2),
    ]


def test_ordered_keys_only_narrow_the_script_order(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    living = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=10_000)
    street = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=6_000)
    _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO, asset=living)
    _bind(db, author, episode_id, "夜·街道#0", operation=Operation.TEXT_TO_VIDEO, asset=street)

    response = _assemble(client, author, episode_id, ordered_keys=["夜·街道#0", "不存在#0"])

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == []
    assert _placed(db, response.json()["cut"]["id"])["trk_video"] == [(street.id, 0, 6 * SECOND)]


def test_assemble_without_any_generated_video_is_rejected(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)

    response = _assemble(client, author, episode_id)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert db.scalars(select(EpisodeCut).where(EpisodeCut.episode_id == episode_id)).all() == []


def test_assemble_refuses_while_the_rough_cut_is_open_in_an_editor(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    video = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=5_000)
    _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO, asset=video)
    cut_id = _assemble(client, author, episode_id).json()["cut"]["id"]
    lease = client.post(
        f"/v1/episode-cuts/{cut_id}/leases",
        headers=auth_header(author),
        json={"browser_instance_id": "browser-a"},
    )
    assert lease.status_code == 201, lease.text

    response = _assemble(client, author, episode_id)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "LEASE_HELD"


def test_only_the_episode_owner_can_assemble(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    episode_id = _episode(client, db, author)
    video = _asset(db, author, media_type=MediaType.VIDEO, duration_ms=5_000)
    _bind(db, author, episode_id, "日·客厅#0", operation=Operation.TEXT_TO_VIDEO, asset=video)
    stranger = make_user(db, email="stranger@example.com", handle="stranger", display_name="路人")

    response = _assemble(client, stranger, episode_id)

    assert response.status_code == 404, response.text
