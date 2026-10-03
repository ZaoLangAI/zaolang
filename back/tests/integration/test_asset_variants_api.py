"""P1-3: `/v1/characters/{id}/looks…`, `/v1/scenes/{id}/variants…` and the
look-aware card / skill-detail responses."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, CreationSkill, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    CreationSkillStatus,
    CreationSkillVisibility,
    MediaType,
    ModerationStatus,
    Visibility,
)
from tests.conftest import auth_header, make_user


def _asset(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="e" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _character(client: TestClient, author: User) -> dict:
    response = client.post("/v1/characters", json={"name": "林夏"}, headers=auth_header(author))
    assert response.status_code == 201
    return response.json()


def test_a_card_lists_its_looks_and_anchor(client: TestClient, db: Session, author: User) -> None:
    character = _character(client, author)
    assert [look["name"] for look in character["looks"]] == ["默认造型"]
    assert character["anchor_entry_id"] is None


def test_looks_and_entries_round_trip(client: TestClient, db: Session, author: User) -> None:
    character = _character(client, author)
    headers = auth_header(author)
    base = f"/v1/characters/{character['id']}"
    default_id = character["looks"][0]["id"]

    look = client.post(
        f"{base}/looks",
        json={"name": "婚礼", "description": "白色婚纱", "presets": {"age_stage": "youth"}},
        headers=headers,
    )
    assert look.status_code == 201
    look_id = look.json()["id"]
    assert look.json()["presets"] == {"age_stage": "youth"}

    sheet = _asset(db, author)
    entry = client.post(
        f"{base}/looks/{look_id}/entries",
        json={"asset_id": sheet.id, "entry_type": "character_sheet", "view": "front"},
        headers=headers,
    )
    assert entry.status_code == 201
    entry_id = entry.json()["id"]
    assert entry.json()["url"]

    moved = client.patch(
        f"{base}/entries/{entry_id}",
        json={"variant_id": default_id, "label": "定稿"},
        headers=headers,
    )
    assert moved.status_code == 200
    anchor = client.post(f"{base}/entries/{moved.json()['id']}:anchor", headers=headers)
    assert anchor.status_code == 200 and anchor.json()["is_anchor"] is True

    detail = client.get(base, headers=headers).json()
    assert detail["anchor_entry_id"] == anchor.json()["id"]
    assert detail["reference_assets"][0]["asset_id"] == sheet.id

    assert client.delete(f"{base}/looks/{default_id}", headers=headers).status_code == 422
    assert client.delete(f"{base}/looks/{look_id}", headers=headers).status_code == 204
    assert client.delete(f"{base}/entries/{moved.json()['id']}", headers=headers).status_code == 204


def test_someone_elses_card_asset_or_entry_is_a_404(
    client: TestClient, db: Session, author: User
) -> None:
    character = _character(client, author)
    stranger = make_user(db, email="stranger@example.com", handle="stranger", display_name="路人")
    base = f"/v1/characters/{character['id']}"
    look_id = character["looks"][0]["id"]

    assert (
        client.post(
            f"{base}/looks", json={"name": "偷看"}, headers=auth_header(stranger)
        ).status_code
        == 404
    )
    foreign = _asset(db, stranger)
    response = client.post(
        f"{base}/looks/{look_id}/entries",
        json={"asset_id": foreign.id, "entry_type": "other"},
        headers=auth_header(author),
    )
    assert response.status_code == 404
    assert (
        client.patch(
            f"{base}/entries/ske_missing", json={"label": "x"}, headers=auth_header(author)
        ).status_code
        == 404
    )


def test_entry_type_and_view_are_validated_per_card(
    client: TestClient, db: Session, author: User
) -> None:
    character = _character(client, author)
    base = f"/v1/characters/{character['id']}"
    look_id = character["looks"][0]["id"]
    asset = _asset(db, author)
    bad_type = client.post(
        f"{base}/looks/{look_id}/entries",
        json={"asset_id": asset.id, "entry_type": "master"},
        headers=auth_header(author),
    )
    assert bad_type.status_code == 422
    bad_view = client.post(
        f"{base}/looks/{look_id}/entries",
        json={"asset_id": asset.id, "entry_type": "view", "view": "establishing"},
        headers=auth_header(author),
    )
    assert bad_view.status_code == 422


def test_scene_variants_take_vocabulary_presets(
    client: TestClient, db: Session, author: User
) -> None:
    scene = client.post("/v1/scenes", json={"name": "客厅"}, headers=auth_header(author)).json()
    assert [v["name"] for v in scene["variants"]] == ["主场景"]
    base = f"/v1/scenes/{scene['id']}"
    ok = client.post(
        f"{base}/variants",
        json={"name": "黄昏雨", "presets": {"lighting": "dusk", "weather": "rain"}},
        headers=auth_header(author),
    )
    assert ok.status_code == 201
    assert ok.json()["presets"] == {"lighting": "dusk", "weather": "rain"}
    bad = client.post(
        f"{base}/variants",
        json={"name": "正午", "presets": {"lighting": "noon"}},
        headers=auth_header(author),
    )
    assert bad.status_code == 422

    first, second = _asset(db, author), _asset(db, author)
    for asset in (first, second):
        added = client.post(
            f"{base}/variants/{ok.json()['id']}/entries",
            json={"asset_id": asset.id, "entry_type": "master"},
            headers=auth_header(author),
        )
        assert added.status_code == 201
    variant = next(
        v
        for v in client.get(base, headers=auth_header(author)).json()["variants"]
        if v["name"] == "黄昏雨"
    )
    # One master per variant: the newer one wins, the older becomes a shot.
    assert [(e["asset_id"], e["entry_type"]) for e in variant["entries"]] == [
        (first.id, "shot"),
        (second.id, "master"),
    ]


def test_editing_a_published_card_withdraws_it(
    client: TestClient, db: Session, author: User
) -> None:
    character = _character(client, author)
    skill = db.get(CreationSkill, character["id"])
    assert skill is not None
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()
    client.post(
        f"/v1/characters/{character['id']}/looks",
        json={"name": "战甲"},
        headers=auth_header(author),
    )
    db.expire_all()
    assert db.get(CreationSkill, character["id"]).status == CreationSkillStatus.DRAFT  # type: ignore[union-attr]


def test_skill_detail_shows_signed_looks_not_raw_reference_ids(
    client: TestClient, db: Session, author: User
) -> None:
    character = _character(client, author)
    base = f"/v1/characters/{character['id']}"
    sheet = _asset(db, author)
    client.post(
        f"{base}/looks/{character['looks'][0]['id']}/entries",
        json={"asset_id": sheet.id, "entry_type": "character_sheet", "view": "front"},
        headers=auth_header(author),
    )
    detail = client.get(f"/v1/skills/{character['id']}", headers=auth_header(author))
    assert detail.status_code == 200
    body = detail.json()
    assert "reference_assets" not in body["params"].get("character", {})
    assert body["asset_variants"][0]["entries"][0]["asset_id"] == sheet.id
    assert body["asset_variants"][0]["entries"][0]["url"]


def test_scene_cards_cannot_be_written_through_skills(
    client: TestClient, db: Session, author: User
) -> None:
    response = client.post(
        "/v1/skills",
        json={"title": "偷渡场景", "category": "scene_asset", "params": {}},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def _generated_sheets(db: Session, author: User, character_id: str, count: int) -> list[str]:
    """Files `count` front sheets the way a job's write-back does: the
    first is approved, the rest wait as candidates."""
    from app.domain.characters import service as characters_service

    ids = []
    for _ in range(count):
        asset = _asset(db, author)
        characters_service.append_reference_asset(
            db,
            user_id=author.id,
            character_id=character_id,
            asset_id=asset.id,
            view="front",
            generated=True,
        )
        ids.append(asset.id)
    db.flush()
    return ids


def test_approving_a_candidate_swaps_it_in(client: TestClient, db: Session, author: User) -> None:
    character = _character(client, author)
    base = f"/v1/characters/{character['id']}"
    first, second = _generated_sheets(db, author, character["id"], 2)

    card = client.get(base, headers=auth_header(author)).json()
    by_asset = {e["asset_id"]: e for e in card["looks"][0]["entries"]}
    assert by_asset[second]["status"] == "candidate"
    # The flat projection (iOS, older readers) shows the approved sheet only.
    assert [e["asset_id"] for e in card["reference_assets"]] == [first]

    approved = client.post(
        f"{base}/entries/{by_asset[second]['id']}:approve", headers=auth_header(author)
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    card = client.get(base, headers=auth_header(author)).json()
    by_asset = {e["asset_id"]: e for e in card["looks"][0]["entries"]}
    assert by_asset[first]["status"] == "candidate"
    assert card["anchor_entry_id"] == by_asset[second]["id"]


def test_approving_is_owner_only_and_withdraws_a_published_card(
    client: TestClient, db: Session, author: User
) -> None:
    character = _character(client, author)
    base = f"/v1/characters/{character['id']}"
    _, second = _generated_sheets(db, author, character["id"], 2)
    card = client.get(base, headers=auth_header(author)).json()
    entry_id = next(e["id"] for e in card["looks"][0]["entries"] if e["asset_id"] == second)
    stranger = make_user(db, email="approver@example.com", handle="approver", display_name="路人")

    assert (
        client.post(f"{base}/entries/{entry_id}:approve", headers=auth_header(stranger)).status_code
        == 404
    )

    skill = db.get(CreationSkill, character["id"])
    assert skill is not None
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()
    client.post(f"{base}/entries/{entry_id}:approve", headers=auth_header(author))
    db.expire_all()
    assert db.get(CreationSkill, character["id"]).status == CreationSkillStatus.DRAFT  # type: ignore[union-attr]


def test_skill_detail_hides_candidates(client: TestClient, db: Session, author: User) -> None:
    character = _character(client, author)
    first, _ = _generated_sheets(db, author, character["id"], 2)
    body = client.get(f"/v1/skills/{character['id']}", headers=auth_header(author)).json()
    assert [e["asset_id"] for e in body["asset_variants"][0]["entries"]] == [first]


def test_an_upload_can_become_the_cards_first_anchor(
    client: TestClient, db: Session, author: User
) -> None:
    """The library's 上传图片 files an approved image at once, so it claims
    the automatic anchor the same way a generated one does — a scene whose
    master was uploaded by hand still gives its matrix cells a master."""
    headers = auth_header(author)
    scene = client.post("/v1/scenes", json={"name": "客厅"}, headers=headers).json()
    scene_base = f"/v1/scenes/{scene['id']}"
    master = client.post(
        f"{scene_base}/variants/{scene['variants'][0]['id']}/entries",
        json={"asset_id": _asset(db, author).id, "entry_type": "master"},
        headers=headers,
    )
    assert master.status_code == 201
    assert client.get(scene_base, headers=headers).json()["anchor_entry_id"] == master.json()["id"]

    character = _character(client, author)
    base = f"/v1/characters/{character['id']}"
    default_id = character["looks"][0]["id"]
    wedding = client.post(f"{base}/looks", json={"name": "婚礼"}, headers=headers).json()
    outfit_sheet = client.post(
        f"{base}/looks/{wedding['id']}/entries",
        json={"asset_id": _asset(db, author).id, "entry_type": "character_sheet", "view": "front"},
        headers=headers,
    )
    assert outfit_sheet.status_code == 201
    assert client.get(base, headers=headers).json()["anchor_entry_id"] is None

    sheet = client.post(
        f"{base}/looks/{default_id}/entries",
        json={"asset_id": _asset(db, author).id, "entry_type": "character_sheet", "view": "front"},
        headers=headers,
    ).json()
    assert client.get(base, headers=headers).json()["anchor_entry_id"] == sheet["id"]
    portrait = client.post(
        f"{base}/looks/{default_id}/entries",
        json={"asset_id": _asset(db, author).id, "entry_type": "identity_portrait"},
        headers=headers,
    ).json()
    assert client.get(base, headers=headers).json()["anchor_entry_id"] == portrait["id"]
