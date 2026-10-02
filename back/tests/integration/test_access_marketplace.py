"""HTTP contract for paid work/skill unlocks and parameter leakage."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.skill_library import service as skill_library
from app.models import AccessGrant, User
from app.models.base import new_id
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    Visibility,
)
from tests.conftest import auth_header
from tests.factories import make_work


def _fund(db: Session, user: User, amount: int = 100) -> None:
    credits.grant(db, user.id, amount, idempotency_key=new_id("grant"))
    db.commit()


def _publish_skill(
    db: Session, owner: User, *, access_credits: int = 8, title: str = "黄金时刻镜头"
):
    skill = skill_library.create(
        db,
        owner_user_id=owner.id,
        title=title,
        description="付费镜头",
        category=CreationSkillCategory.LENS,
        params_json={"prompt_suffix": "golden hour, anamorphic flare"},
        cover_asset_id=None,
        access_credits=access_credits,
    )
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.commit()
    return skill


def test_paid_work_hides_params_until_unlocked(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, access_credits=10)
    db.commit()

    locked = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert locked["can_remix"] is False
    assert locked["remixable"] is True
    assert locked["remix_block_reason"] == "needs_unlock"
    assert locked["reusable_params"] is None
    assert locked["viewer_unlocked"] is False
    assert locked["access_credits"] == 10

    draft = client.post(
        "/v1/drafts",
        json={"source_work_id": work.id},
        headers=auth_header(remixer),
    )
    assert draft.status_code == 402, draft.text
    assert draft.json()["error"]["code"] == "ACCESS_REQUIRED"

    job = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "text_to_image",
            "quality_tier": "standard",
            "params": {"prompt": "二创"},
            "source_work_id": work.id,
        },
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert job.status_code == 402, job.text

    _fund(db, remixer, 100)
    unlocked = client.post(
        f"/v1/works/{work.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["viewer_unlocked"] is True
    assert unlocked.json()["already_held"] is False

    replay = client.post(
        f"/v1/works/{work.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_held"] is True

    opened = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert opened["can_remix"] is True
    assert opened["reusable_params"]["seed"] == 42
    assert opened["viewer_unlocked"] is True

    first = client.post(
        "/v1/drafts", json={"source_work_id": work.id}, headers=auth_header(remixer)
    )
    second = client.post(
        "/v1/drafts", json={"source_work_id": work.id}, headers=auth_header(remixer)
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["license"]["license_type"] == "zaolang_paid_remix"


def test_author_sees_own_paid_params(client: TestClient, db: Session, author: User) -> None:
    work, _ = make_work(db, author, access_credits=10)
    db.commit()

    body = client.get(f"/v1/works/{work.id}", headers=auth_header(author)).json()
    assert body["can_remix"] is True
    assert body["viewer_unlocked"] is True
    assert body["reusable_params"]["seed"] == 42


def test_view_only_after_purchase_blocks_new_drafts(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, access_credits=10)
    db.commit()
    _fund(db, remixer, 100)
    client.post(
        f"/v1/works/{work.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    client.patch(
        f"/v1/works/{work.id}/visibility",
        json={"visibility": Visibility.PUBLIC_VIEW_ONLY.value},
        headers=auth_header(author),
    )

    draft = client.post(
        "/v1/drafts",
        json={"source_work_id": work.id},
        headers=auth_header(remixer),
    )
    assert draft.status_code == 409, draft.text
    assert draft.json()["error"]["code"] == "LICENSE_NOT_REMIXABLE"


def test_paid_skill_hides_params_until_unlocked(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    skill = _publish_skill(db, author)

    listed = client.get("/v1/skills/public?access=paid").json()
    card = next(item for item in listed["items"] if item["id"] == skill.id)
    assert card["access_credits"] == 8
    assert card["viewer_unlocked"] is False
    assert "params" not in card

    detail = client.get(f"/v1/skills/{skill.id}", headers=auth_header(remixer)).json()
    assert detail["params"] == {}
    assert detail["viewer_unlocked"] is False

    apply_locked = client.post(f"/v1/skills/{skill.id}/apply", headers=auth_header(remixer))
    assert apply_locked.status_code == 402, apply_locked.text
    assert apply_locked.json()["error"]["code"] == "ACCESS_REQUIRED"

    _fund(db, remixer, 100)
    unlock = client.post(
        f"/v1/skills/{skill.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert unlock.status_code == 200, unlock.text

    applied = client.post(f"/v1/skills/{skill.id}/apply", headers=auth_header(remixer))
    assert applied.status_code == 200, applied.text
    assert applied.json()["params"]["prompt_suffix"] == "golden hour, anamorphic flare"


def test_skill_price_change_does_not_unpublish(
    client: TestClient, db: Session, author: User
) -> None:
    skill = _publish_skill(db, author, access_credits=8)

    priced = client.patch(
        f"/v1/skills/{skill.id}/pricing",
        json={"access_credits": 20},
        headers=auth_header(author),
    )
    assert priced.status_code == 200, priced.text
    assert priced.json()["access_credits"] == 20
    assert priced.json()["status"] == CreationSkillStatus.PUBLISHED.value

    edited = client.patch(
        f"/v1/skills/{skill.id}",
        json={
            "title": "黄金时刻镜头 · 改",
            "description": "付费镜头",
            "category": "lens",
            "params": {"prompt_suffix": "changed"},
        },
        headers=auth_header(author),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == CreationSkillStatus.DRAFT.value


def test_insufficient_credits_do_not_write_a_grant(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, access_credits=10)
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert response.status_code == 402, response.text
    assert response.json()["error"]["code"] == "INSUFFICIENT_CREDITS"
    assert (
        db.scalar(
            select(func.count())
            .select_from(AccessGrant)
            .where(AccessGrant.buyer_user_id == remixer.id)
        )
        == 0
    )


def test_self_unlock_writes_no_ledger(client: TestClient, db: Session, author: User) -> None:
    work, _ = make_work(db, author, access_credits=10)
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/unlock",
        headers={**auth_header(author), "Idempotency-Key": new_id("idk")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["already_held"] is True
    assert response.json()["grant"] is None


def test_works_and_skills_can_be_filtered_by_access(
    client: TestClient, db: Session, author: User
) -> None:
    free, _ = make_work(db, author, title="免费二创")
    paid, _ = make_work(db, author, title="付费二创", access_credits=10)
    db.commit()
    _publish_skill(db, author, title="付费技能", access_credits=8)
    _publish_skill(db, author, title="免费技能", access_credits=0)

    mixed = client.get("/v1/works").json()["items"]
    assert any(item["id"] == free.id for item in mixed)
    assert any(item["id"] == paid.id for item in mixed)

    paid_works = client.get("/v1/works?access=paid").json()["items"]
    assert any(item["id"] == paid.id for item in paid_works)
    assert all(item["access_credits"] > 0 for item in paid_works)

    free_works = client.get("/v1/works?access=free&remixable=true").json()["items"]
    assert any(item["id"] == free.id for item in free_works)
    assert all(item["access_credits"] == 0 for item in free_works)

    paid_skills = client.get("/v1/skills/public?access=paid").json()["items"]
    assert all(item["access_credits"] > 0 for item in paid_skills)
