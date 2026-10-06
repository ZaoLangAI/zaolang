"""Admin `/style-gallery` CRUD and its public `/v1/style-gallery` read side."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.models import GenerationJob, User
from app.models.base import new_id
from tests.conftest import admin_header, auth_header


def _create_payload(**overrides: object) -> dict:
    payload = {
        "slug": "anime-japanese",
        "label_zh": "日漫",
        "label_en": "Japanese anime",
        "label_ja": "日本アニメ",
        "description": "赛璐璐渲染，锐利线条。",
        "cover_asset_id": None,
        "params": {"aspect_ratio": "9:16", "prompt_suffix": "japanese anime style"},
        "sort_order": 0,
    }
    payload.update(overrides)
    return payload


def test_admin_can_create_list_and_update_an_entry(client: TestClient, admin: User) -> None:
    created = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert created.json()["is_active"] is True

    listed = client.get("/v1/admin/style-gallery", headers=admin_header(admin))
    assert listed.status_code == 200
    assert any(item["id"] == entry_id for item in listed.json()["items"])

    updated = client.put(
        f"/v1/admin/style-gallery/{entry_id}",
        json={
            "label_zh": "日漫风",
            "label_en": "Japanese anime style",
            "label_ja": "日本アニメ風",
            "description": "更新后的描述。",
            "cover_asset_id": None,
            "params": {"aspect_ratio": "16:9", "prompt_suffix": "anime style, updated"},
            "sort_order": 1,
            "is_active": False,
        },
        headers=admin_header(admin),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["label_zh"] == "日漫风"
    assert body["is_active"] is False


def test_duplicate_slug_is_rejected(client: TestClient, admin: User) -> None:
    first = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    assert second.status_code == 409


def test_public_listing_only_shows_active_entries(client: TestClient, admin: User) -> None:
    created = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    entry_id = created.json()["id"]

    public_before = client.get("/v1/style-gallery")
    assert public_before.status_code == 200
    assert any(item["id"] == entry_id for item in public_before.json()["items"])

    client.put(
        f"/v1/admin/style-gallery/{entry_id}",
        json={**_create_payload(), "is_active": False},
        headers=admin_header(admin),
    )

    public_after = client.get("/v1/style-gallery")
    assert not any(item["id"] == entry_id for item in public_after.json()["items"])
    assert client.get(f"/v1/style-gallery/{entry_id}").status_code == 404


def test_applying_an_entry_bumps_its_usage_counter(client: TestClient, admin: User) -> None:
    created = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    entry_id = created.json()["id"]

    response = client.post(f"/v1/style-gallery/{entry_id}/apply", headers=auth_header(admin))
    assert response.status_code == 200, response.text
    assert response.json()["apply_count"] == 1


def test_deleting_requires_confirmation_and_a_reason(client: TestClient, admin: User) -> None:
    created = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    entry_id = created.json()["id"]

    unconfirmed = client.post(
        f"/v1/admin/style-gallery/{entry_id}/delete",
        json={"reason": "下线过期风格", "confirm": False},
        headers=admin_header(admin),
    )
    assert unconfirmed.status_code == 422

    confirmed = client.post(
        f"/v1/admin/style-gallery/{entry_id}/delete",
        json={"reason": "下线过期风格", "confirm": True},
        headers=admin_header(admin),
    )
    assert confirmed.status_code == 200
    assert not any(item["id"] == entry_id for item in confirmed.json()["items"])


def test_submitting_a_job_persists_style_gallery_id(
    client: TestClient, db: Session, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.workers.tasks.dispatch_generation", lambda job: None)
    credits_service.grant(db, admin.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()

    created = client.post(
        "/v1/admin/style-gallery", json=_create_payload(), headers=admin_header(admin)
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "text_to_image",
            "quality_tier": "standard",
            "params": {
                "prompt": "海边的黄昏",
                "aspect_ratio": "16:9",
                "asset_kind": "scene",
                "style_gallery_id": entry_id,
            },
        },
        headers={**auth_header(admin), "Idempotency-Key": new_id("idk")},
    )
    assert response.status_code == 202, response.text
    job = db.get(GenerationJob, response.json()["id"])
    assert job is not None
    assert job.request_json["style_gallery_id"] == entry_id
