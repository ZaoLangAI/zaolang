"""Consumer API contract: auth, discovery, error envelope and ownership."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header
from tests.factories import make_work


def test_register_returns_a_session_and_a_starter_grant(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "newcomer@example.com",
            "password": "Zaolang2026",
            "display_name": "新来的",
            "handle": "newcomer",
            "age_confirmed": True,
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["available_credits"] > 0


def test_registration_refuses_an_unconfirmed_age_gate(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "minor@example.com",
            "password": "Zaolang2026",
            "display_name": "未确认",
            "handle": "unconfirmed",
            "age_confirmed": False,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_login_does_not_distinguish_unknown_email_from_wrong_password(
    client: TestClient, author: User
) -> None:
    unknown = client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "Zaolang2026"}
    )
    wrong = client.post(
        "/v1/auth/login", json={"email": author.email, "password": "WrongPassword1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_every_error_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/v1/works/wrk_does_not_exist")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers["x-request-id"]


def test_a_private_work_is_indistinguishable_from_a_missing_one(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PRIVATE)
    db.commit()

    response = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer))
    assert response.status_code == 404


def test_discovery_lists_only_public_active_works(
    client: TestClient, db: Session, author: User
) -> None:
    public, _ = make_work(db, author, title="公开作品")
    private, _ = make_work(db, author, title="私密作品", visibility=Visibility.PRIVATE)
    db.commit()

    ids = {item["id"] for item in client.get("/v1/works").json()["items"]}
    assert public.id in ids
    assert private.id not in ids


def test_work_list_includes_output_duration(client: TestClient, db: Session, author: User) -> None:
    clip, clip_version = make_work(db, author, title="有时长")
    still, still_version = make_work(db, author, title="静帧")
    video = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=2048,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        duration_ms=12_000,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    image = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=512,
        checksum_sha256="d" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add_all([video, image])
    db.flush()
    clip_version.primary_output_asset_id = video.id
    still_version.primary_output_asset_id = image.id
    db.commit()

    by_id = {item["id"]: item for item in client.get("/v1/works").json()["items"]}
    assert by_id[clip.id]["duration_ms"] == 12_000
    assert by_id[still.id]["duration_ms"] is None


def test_liking_is_idempotent(client: TestClient, db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author)
    db.commit()

    first = client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    second = client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    assert first.json()["count"] == second.json()["count"] == 1


def test_a_protected_endpoint_rejects_an_anonymous_caller(client: TestClient) -> None:
    response = client.get("/v1/credits/balance")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_visibility_cannot_be_changed_by_a_non_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author)
    db.commit()

    response = client.patch(
        f"/v1/works/{work.id}/visibility",
        json={"visibility": Visibility.PRIVATE.value},
        headers=auth_header(remixer),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_view_only_work_hides_its_reusable_parameters(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """The licence is meaningless if the prompt ships with a view-only work."""
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)
    db.commit()

    body = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert body["can_remix"] is False
    assert body["reusable_params"] is None


def test_a_remixable_work_exposes_its_parameters(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_REMIXABLE)
    db.commit()

    body = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert body["can_remix"] is True
    assert body["reusable_params"]["seed"] == 42


def test_quote_is_returned_before_any_credits_move(
    client: TestClient, db: Session, author: User
) -> None:
    before = client.get("/v1/credits/balance", headers=auth_header(author)).json()
    quote = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": "text_to_image", "quality_tier": "standard"},
        headers=auth_header(author),
    )
    after = client.get("/v1/credits/balance", headers=auth_header(author)).json()

    assert quote.status_code == 200
    assert quote.json()["credits"] > 0
    assert before["available"] == after["available"]


def test_generation_job_validation_exposes_the_specific_frame_conflict(
    client: TestClient, author: User
) -> None:
    """A model-level first/last-frame clash used to land as
    `message=请求参数不合法` plus `fields[""]` with a Pydantic `Value error,`
    prefix — the studio banner and script-batch row only read `message`.
    The envelope now carries the specific sentence, keyed on `params`."""
    expected = "首尾帧不能与角色参考、场景参考同时使用。请取消首尾帧，或改回图片/视频参考。"
    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "image_to_video",
            "quality_tier": "standard",
            "params": {
                "prompt": "夜门",
                "aspect_ratio": "16:9",
                "duration_seconds": 8,
                "character_ids": ["sk_char"],
                "scene_ids": ["sk_scene"],
                "video_options": {
                    "resolution": "1080p",
                    "reference_mode": "frame_images",
                    "first_frame_asset_id": "ast_first",
                },
            },
        },
        headers=auth_header(author),
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_FAILED"
    assert body["message"] == expected
    assert body["details"]["fields"]["params"] == expected
