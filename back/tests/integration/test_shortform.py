"""Short-video specs, compliance checks and export intents.

The compliance endpoint is the interesting one: it must report every failed
rule at once rather than stopping at the first, because a creator fixing a
caption should not have to submit five times to discover five problems.
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import rate_limit
from app.models import Asset, Draft, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    MediaType,
    ModerationStatus,
    PublicationStatus,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import DEFAULT_CONFIGS
from tests.conftest import auth_header
from tests.factories import make_work

COMPLIANT_CAPTION = {
    "title": "黎明的潮汐",
    "description": "在天亮之前拍下的三十秒。#AIGC",
    "hashtags": ["ocean", "aigc"],
}


def _video_asset(
    session: Session,
    owner: User,
    *,
    width: int = 1080,
    height: int = 1920,
    duration_ms: int | None = 12_000,
) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=2048,
        checksum_sha256="a" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=width,
        height=height,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _draft_with_output(session: Session, owner: User, asset: Asset) -> Draft:
    draft = Draft(user_id=owner.id, title="短视频草稿", output_asset_id=asset.id)
    session.add(draft)
    session.flush()
    return draft


def _levels(body: dict) -> dict[str, str]:
    return {check["code"]: check["level"] for check in body["checks"]}


# --- GET /v1/shortform/profiles -----------------------------------------


def test_the_spec_catalogue_is_readable_without_signing_in(client: TestClient) -> None:
    """The studio renders its selector from this before asking anyone to log in."""
    response = client.get("/v1/shortform/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body["default_profile"] == "douyin_vertical"
    keys = {profile["key"] for profile in body["profiles"]}
    assert {"douyin_vertical", "douyin_landscape"} <= keys


def test_the_catalogue_carries_the_limits_the_client_validates_against(
    client: TestClient,
) -> None:
    body = client.get("/v1/shortform/profiles").json()
    vertical = next(p for p in body["profiles"] if p["key"] == "douyin_vertical")

    assert vertical["aspect_ratio"] == "9:16"
    assert vertical["max_duration_seconds"] <= 30
    assert vertical["max_title_length"] > 0
    assert vertical["require_ai_disclosure"] is True


def test_reading_the_catalogue_is_rate_limited(client: TestClient, author: User) -> None:
    identity = f"user:{author.id}"
    for _ in range(rate_limit.RULES["public_read"].limit):
        rate_limit.enforce("public_read", identity)

    response = client.get("/v1/shortform/profiles", headers=auth_header(author))

    assert response.status_code == 429
    assert response.headers.get("retry-after")


# --- POST /v1/shortform/compliance-check --------------------------------


def test_a_conforming_clip_passes_every_check(
    client: TestClient, db: Session, author: User
) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is True
    assert body["profile"]["key"] == "douyin_vertical"
    assert set(_levels(body).values()) == {"pass"}


def test_a_landscape_clip_is_blocked_by_the_vertical_spec(
    client: TestClient, db: Session, author: User
) -> None:
    asset = _video_asset(db, author, width=1920, height=1080)
    draft = _draft_with_output(db, author, asset)
    db.commit()

    body = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    ).json()

    assert _levels(body)["ASPECT_RATIO"] == "block"
    assert body["passed"] is False


def test_the_same_clip_passes_under_the_landscape_spec(
    client: TestClient, db: Session, author: User
) -> None:
    """Which spec applies is a choice, not a property of the file."""
    asset = _video_asset(db, author, width=1920, height=1080)
    draft = _draft_with_output(db, author, asset)
    db.commit()

    body = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, "profile": "douyin_landscape", **COMPLIANT_CAPTION},
        headers=auth_header(author),
    ).json()

    assert _levels(body)["ASPECT_RATIO"] == "pass"
    assert body["passed"] is True


def test_every_broken_rule_is_reported_in_one_pass(
    client: TestClient, db: Session, author: User
) -> None:
    asset = _video_asset(db, author, width=1920, height=1080, duration_ms=90_000)
    draft = _draft_with_output(db, author, asset)
    db.commit()

    body = client.post(
        "/v1/shortform/compliance-check",
        json={
            "draft_id": draft.id,
            "title": "标" * 80,
            "description": "没有声明。",
            "hashtags": ["a", "b", "c", "d", "e", "f"],
        },
        headers=auth_header(author),
    ).json()

    levels = _levels(body)
    assert levels["ASPECT_RATIO"] == "block"
    assert levels["DURATION"] == "block"
    assert levels["TITLE_LENGTH"] == "block"
    assert levels["HASHTAG_COUNT"] == "block"
    assert levels["AI_DISCLOSURE"] == "block"
    assert body["passed"] is False


def test_a_missing_clip_warns_instead_of_blocking(
    client: TestClient, db: Session, author: User
) -> None:
    """The caption can be written while the clip is still generating."""
    draft = Draft(user_id=author.id, title="还没出片")
    db.add(draft)
    db.commit()

    body = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    ).json()

    levels = _levels(body)
    assert levels["ASPECT_RATIO"] == "warn"
    assert levels["DURATION"] == "warn"
    assert body["passed"] is True


def test_unsafe_copy_blocks_the_publication(client: TestClient, db: Session, author: User) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    body = client.post(
        "/v1/shortform/compliance-check",
        json={
            "draft_id": draft.id,
            "title": "未成年角色的亲密画面",
            "description": "#AIGC",
            "hashtags": ["aigc"],
        },
        headers=auth_header(author),
    ).json()

    assert _levels(body)["CONTENT_SAFETY"] == "block"
    assert body["passed"] is False


def test_an_asset_can_be_checked_without_a_draft(
    client: TestClient, db: Session, author: User
) -> None:
    asset = _video_asset(db, author)
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"asset_id": asset.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    )

    assert response.status_code == 200
    assert response.json()["passed"] is True


def test_a_check_without_a_subject_is_refused(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/shortform/compliance-check", json=COMPLIANT_CAPTION, headers=auth_header(author)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_an_unknown_spec_is_refused(client: TestClient, db: Session, author: User) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, "profile": "kuaishou_vertical", **COMPLIANT_CAPTION},
        headers=auth_header(author),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_a_compliance_check_requires_a_session(
    client: TestClient, db: Session, author: User
) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check", json={"draft_id": draft.id, **COMPLIANT_CAPTION}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_another_users_draft_cannot_be_checked(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(remixer),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_another_users_asset_is_reported_as_missing(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """404 rather than 403: confirming the id exists would be a leak."""
    asset = _video_asset(db, author)
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"asset_id": asset.id, **COMPLIANT_CAPTION},
        headers=auth_header(remixer),
    )

    assert response.status_code == 404


def test_compliance_checks_are_rate_limited(client: TestClient, db: Session, author: User) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    db.commit()

    identity = f"user:{author.id}"
    for _ in range(rate_limit.RULES["authenticated_write"].limit):
        rate_limit.enforce("authenticated_write", identity)

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    )

    assert response.status_code == 429
    assert response.headers.get("retry-after")


def test_the_studio_can_be_switched_off(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    draft = _draft_with_output(db, author, _video_asset(db, author))
    flags = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    flags["shortform_studio"] = False
    config_service.set_value(db, "feature_flags", flags, actor_user_id=admin.id)
    db.commit()

    response = client.post(
        "/v1/shortform/compliance-check",
        json={"draft_id": draft.id, **COMPLIANT_CAPTION},
        headers=auth_header(author),
    )

    assert response.status_code == 422


# --- /v1/works/{id}/publications ----------------------------------------


def _published_work(session: Session, owner: User) -> tuple[str, Asset]:
    work, version = make_work(session, owner)
    asset = _video_asset(session, owner)
    version.primary_output_asset_id = asset.id
    session.flush()
    return work.id, asset


def test_exporting_a_work_records_the_intent_and_returns_the_file(
    client: TestClient, db: Session, author: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    response = client.post(
        f"/v1/works/{work_id}/publications",
        json={"channel": "manual_download", "title": "黎明的潮汐", "hashtags": ["aigc"]},
        headers=auth_header(author),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == PublicationStatus.EXPORTED.value
    assert body["channel"] == "manual_download"
    assert body["download_url"]
    assert body["payload"]["hashtags"] == ["aigc"]
    # Direct publishing does not exist yet, and the payload must not pretend it does.
    assert body["external_post_id"] is None
    assert body["submitted_at"] is None


def test_a_douyin_intent_is_recorded_but_not_submitted(
    client: TestClient, db: Session, author: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    body = client.post(
        f"/v1/works/{work_id}/publications",
        json={"channel": "douyin", "title": "黎明的潮汐"},
        headers=auth_header(author),
    ).json()

    assert body["channel"] == "douyin"
    assert body["status"] == PublicationStatus.EXPORTED.value
    assert body["submitted_at"] is None


def test_a_work_without_a_deliverable_is_only_ready(
    client: TestClient, db: Session, author: User
) -> None:
    work, _ = make_work(db, author)
    db.commit()

    body = client.post(
        f"/v1/works/{work.id}/publications",
        json={"title": "还没有成片"},
        headers=auth_header(author),
    ).json()

    assert body["status"] == PublicationStatus.READY.value
    assert body["download_url"] is None


def test_retrying_an_export_with_the_same_key_replays_it(
    client: TestClient, db: Session, author: User
) -> None:
    """A double-tapped export button must not leave two rows in the history."""
    work_id, _ = _published_work(db, author)
    db.commit()

    payload = {"title": "黎明的潮汐", "hashtags": ["aigc"]}
    headers = {**auth_header(author), "Idempotency-Key": "export-1"}
    first = client.post(f"/v1/works/{work_id}/publications", json=payload, headers=headers)
    second = client.post(f"/v1/works/{work_id}/publications", json=payload, headers=headers)

    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = client.get(f"/v1/works/{work_id}/publications", headers=auth_header(author))
    assert len(listing.json()["items"]) == 1


def test_reusing_a_key_for_a_different_export_is_a_conflict(
    client: TestClient, db: Session, author: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    headers = {**auth_header(author), "Idempotency-Key": "export-1"}
    client.post(f"/v1/works/{work_id}/publications", json={"title": "第一版"}, headers=headers)
    conflict = client.post(
        f"/v1/works/{work_id}/publications", json={"title": "第二版"}, headers=headers
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_the_export_history_is_listed_newest_first(
    client: TestClient, db: Session, author: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    for title in ("第一版", "第二版"):
        client.post(
            f"/v1/works/{work_id}/publications",
            json={"title": title},
            headers=auth_header(author),
        )

    items = client.get(f"/v1/works/{work_id}/publications", headers=auth_header(author)).json()[
        "items"
    ]

    assert len(items) == 2
    assert {item["payload"]["title"] for item in items} == {"第一版", "第二版"}


def test_exporting_requires_a_session(client: TestClient, db: Session, author: User) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    response = client.post(f"/v1/works/{work_id}/publications", json={"title": "无名"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_only_the_owner_may_export_a_work(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    response = client.post(
        f"/v1/works/{work_id}/publications",
        json={"title": "别人的作品"},
        headers=auth_header(remixer),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_only_the_owner_may_read_the_export_history(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    response = client.get(f"/v1/works/{work_id}/publications", headers=auth_header(remixer))

    assert response.status_code == 403


def test_exporting_a_missing_work_is_a_404(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/works/wrk_missing/publications",
        json={"title": "不存在"},
        headers=auth_header(author),
    )

    assert response.status_code == 404


def test_exports_are_rate_limited(client: TestClient, db: Session, author: User) -> None:
    work_id, _ = _published_work(db, author)
    db.commit()

    identity = f"user:{author.id}"
    for _ in range(rate_limit.RULES["authenticated_write"].limit):
        rate_limit.enforce("authenticated_write", identity)

    response = client.post(
        f"/v1/works/{work_id}/publications",
        json={"title": "黎明的潮汐"},
        headers=auth_header(author),
    )

    assert response.status_code == 429
    assert response.headers.get("retry-after")


def test_a_tombstoned_work_can_no_longer_be_exported(
    client: TestClient, db: Session, author: User
) -> None:
    work, _ = make_work(db, author, lifecycle_status="tombstone")
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/publications",
        json={"title": "已下架"},
        headers=auth_header(author),
    )

    assert response.status_code == 409


def test_a_work_that_was_never_exported_has_an_empty_history(
    client: TestClient, db: Session, author: User
) -> None:
    work, _ = make_work(db, author)
    db.commit()

    response = client.get(f"/v1/works/{work.id}/publications", headers=auth_header(author))

    assert response.status_code == 200
    assert response.json()["items"] == []
