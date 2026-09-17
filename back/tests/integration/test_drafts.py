"""Draft list/detail projections, including output media metadata."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.editor import collaborators as collab_service
from app.domain.jobs import service as jobs_service
from app.domain.publishing import service as publishing
from app.models import Asset, Draft, GenerationJob, SeriesCollaborator, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    ImageAssetKind,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    SeriesCollaboratorStatus,
    Visibility,
)
from tests.conftest import auth_header
from tests.factories import make_job


@pytest.mark.parametrize(
    ("media_type", "mime_type", "duration_ms"),
    [
        (MediaType.IMAGE, "image/png", None),
        (MediaType.VIDEO, "video/mp4", 8_000),
    ],
)
def test_draft_response_exposes_output_media_meta(
    client: TestClient,
    db: Session,
    author: User,
    media_type: MediaType,
    mime_type: str,
    duration_ms: int | None,
) -> None:
    asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}",
        media_type=media_type,
        mime_type=mime_type,
        size_bytes=128,
        checksum_sha256="b" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1920,
        height=1080,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None, title="雾谷")
    draft.output_asset_id = asset.id
    db.flush()

    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output_media_type"] == media_type.value
    assert body["output_asset_id"] == asset.id
    assert body["output_url"]
    assert body["width"] == 1920
    assert body["height"] == 1080
    assert body["duration_ms"] == duration_ms


def test_draft_without_output_omits_media_meta(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)

    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output_asset_id"] is None
    assert body["output_url"] is None
    assert body["output_media_type"] is None
    assert body["duration_ms"] is None
    assert body["width"] is None
    assert body["height"] is None


def test_create_draft_derives_title_from_prompt(
    client: TestClient, db: Session, author: User
) -> None:
    response = client.post(
        "/v1/drafts",
        headers=auth_header(author),
        json={"params": {"prompt": "雨夜巷口摊牌\n第二行", "operation": "text_to_image"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["title"] == "雨夜巷口摊牌"


def test_draft_response_fills_title_from_stored_prompt(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "都市霓虹后巷"}
    )
    draft.title = None
    db.flush()

    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "都市霓虹后巷"


def _job_for_draft(db: Session, author: User, draft: Draft, *, asset_kind: str) -> GenerationJob:
    job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_IMAGE)
    job.draft_id = draft.id
    job.request_json = {"prompt": "测试", "asset_kind": asset_kind}
    draft.latest_job_id = job.id
    db.flush()
    return job


def test_list_drafts_is_owner_scoped_and_keeps_own_roster_generations(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    general = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "普通图", "asset_kind": "general"},
    )
    cover = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "封面图", "asset_kind": "cover"},
    )
    character = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "角色图", "asset_kind": "character"},
    )
    scene = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "场景图", "asset_kind": "scene"},
    )
    foreign_character = publishing.create_draft(
        db,
        user_id=remixer.id,
        source_work_id=None,
        params={"prompt": "别人的角色", "asset_kind": "character"},
    )
    foreign_general = publishing.create_draft(
        db,
        user_id=remixer.id,
        source_work_id=None,
        params={"prompt": "别人的图", "asset_kind": "general"},
    )
    _job_for_draft(db, author, character, asset_kind=ImageAssetKind.CHARACTER.value)
    db.flush()

    mine = client.get("/v1/drafts", headers=auth_header(author))
    assert mine.status_code == 200, mine.text
    mine_ids = {item["id"] for item in mine.json()["items"]}
    assert {general.id, cover.id, character.id, scene.id} <= mine_ids
    assert foreign_character.id not in mine_ids
    assert foreign_general.id not in mine_ids

    theirs = client.get("/v1/drafts", headers=auth_header(remixer))
    assert theirs.status_code == 200, theirs.text
    theirs_ids = {item["id"] for item in theirs.json()["items"]}
    assert {foreign_character.id, foreign_general.id} <= theirs_ids
    assert general.id not in theirs_ids
    assert character.id not in theirs_ids

    own = client.get(f"/v1/drafts/{character.id}", headers=auth_header(author))
    assert own.status_code == 200, own.text
    assert own.json()["id"] == character.id

    foreign = client.get(f"/v1/drafts/{foreign_character.id}", headers=auth_header(author))
    assert foreign.status_code == 403


def test_list_drafts_omits_row_whose_output_belongs_to_another_user(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    foreign_asset = Asset(
        owner_user_id=remixer.id,
        object_key=f"test/{new_id('obj')}",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=128,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1024,
        height=1024,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
    )
    own_asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=128,
        checksum_sha256="d" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1024,
        height=1024,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add_all([foreign_asset, own_asset])
    db.flush()
    leaked = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "串号海报"}
    )
    leaked.output_asset_id = foreign_asset.id
    own = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "自己的角色图"}
    )
    own.output_asset_id = own_asset.id
    db.flush()

    response = client.get("/v1/drafts", headers=auth_header(author))
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert own.id in ids
    assert leaked.id not in ids

    detail = client.get(f"/v1/drafts/{leaked.id}", headers=auth_header(author))
    assert detail.status_code == 200, detail.text


def test_list_drafts_hides_episode_generations_after_leaving_collaboration(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    series_id = client.post(
        "/v1/drama-series",
        headers=auth_header(author),
        json={"title": "共创短剧", "target_platforms": ["manual_download"]},
    ).json()["id"]
    episode_id = client.post(
        f"/v1/drama-series/{series_id}/episodes",
        headers=auth_header(author),
        json={"title": "第一集"},
    ).json()["id"]
    membership = SeriesCollaborator(
        series_id=series_id,
        user_id=remixer.id,
        invited_by_user_id=author.id,
        status=SeriesCollaboratorStatus.ACTIVE,
    )
    db.add(membership)
    db.flush()

    personal = publishing.create_draft(
        db,
        user_id=remixer.id,
        source_work_id=None,
        params={"prompt": "自己的图", "asset_kind": "general"},
    )
    collab = client.post(
        "/v1/drafts",
        headers=auth_header(remixer),
        json={"params": {"prompt": "共创镜头", "link_episode_id": episode_id}},
    )
    assert collab.status_code == 201, collab.text
    collab_id = collab.json()["id"]
    owner_clip = client.post(
        "/v1/drafts",
        headers=auth_header(author),
        json={"params": {"prompt": "作者镜头", "link_episode_id": episode_id}},
    )
    assert owner_clip.status_code == 201, owner_clip.text
    owner_clip_id = owner_clip.json()["id"]

    while_member = client.get("/v1/drafts", headers=auth_header(remixer))
    assert while_member.status_code == 200, while_member.text
    member_ids = {item["id"] for item in while_member.json()["items"]}
    assert {personal.id, collab_id} <= member_ids
    assert owner_clip_id not in member_ids

    collab_service.remove(
        db, actor_user_id=remixer.id, series_id=series_id, collaborator_id=membership.id
    )
    db.flush()

    after_leave = client.get("/v1/drafts", headers=auth_header(remixer))
    assert after_leave.status_code == 200, after_leave.text
    left_ids = {item["id"] for item in after_leave.json()["items"]}
    assert personal.id in left_ids
    assert collab_id not in left_ids

    owner_list = client.get("/v1/drafts", headers=auth_header(author))
    assert owner_list.status_code == 200, owner_list.text
    owner_ids = {item["id"] for item in owner_list.json()["items"]}
    assert owner_clip_id in owner_ids
    assert collab_id not in owner_ids

    series_list = client.get("/v1/drama-series", headers=auth_header(remixer))
    assert series_list.status_code == 200, series_list.text
    assert series_id not in {item["id"] for item in series_list.json()}

    still_owned = client.get(f"/v1/drafts/{collab_id}", headers=auth_header(remixer))
    assert still_owned.status_code == 200, still_owned.text


def test_point_draft_at_job_stamps_roster_asset_kind(db: Session, author: User) -> None:
    draft = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "角色"}
    )
    job = make_job(db, author, status=JobStatus.CREATED, operation=Operation.TEXT_TO_IMAGE)
    job.draft_id = draft.id
    job.request_json = {"prompt": "角色", "asset_kind": ImageAssetKind.CHARACTER.value}
    db.flush()

    jobs_service._point_draft_at_job(
        db, user_id=author.id, draft_id=draft.id, job_id=job.id, sandbox=False
    )
    db.flush()
    db.expire(draft)
    assert draft.latest_job_id == job.id
    assert draft.params_json["asset_kind"] == ImageAssetKind.CHARACTER.value
