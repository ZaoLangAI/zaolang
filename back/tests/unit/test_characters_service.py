"""Character library service — the adapter layer over `CreationSkill`
(`category=CHARACTER`), see `app.domain.characters.service.CharacterView`.

`test_reference_asset_writes_survive_a_fresh_reload_from_the_database` and
its scene-side sibling in `test_scenes_service.py` guard a real bug this
module used to have: `_payload`/`_reference_assets` used to hand back the
*same* dict/entry objects stored inside `CreationSkill.params_json`, and
every mutator (`append_reference_asset`, `update_reference_asset`,
`update_character`) mutated them in place before reassigning the column.
That mutates the JSON column's "before" value together with the "after"
value it is compared against at flush time, so SQLAlchemy sees no change and
silently skips the `UPDATE` — the edit looks like it worked for the rest of
the request (the in-memory object is correct) but is gone the moment the row
is reloaded fresh. `session.expire_all()` forces exactly that reload without
depending on GC timing.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import CharacterViewAngle, MediaType
from tests.conftest import make_user


def _asset(db: Session, owner: User, *, media_type: str = MediaType.IMAGE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="image/png" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


# ---- CRUD ------------------------------------------------------------------


def test_create_get_update_delete_round_trip(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description="外冷内热的便利店店员",
        reference_asset_ids=[],
        voice_description="低沉、克制",
    )
    fetched = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert fetched.name == "林夏"
    assert fetched.description == "外冷内热的便利店店员"
    assert fetched.voice_description == "低沉、克制"

    updated = characters_service.update_character(
        db, user_id=author.id, character_id=character.id, name="林夏（改）", description="新设定"
    )
    assert updated.name == "林夏（改）"
    assert updated.description == "新设定"

    characters_service.delete_character(db, user_id=author.id, character_id=character.id)
    with pytest.raises(NotFound):
        characters_service.get_character(db, user_id=author.id, character_id=character.id)


def test_a_character_is_scoped_to_its_owner(db: Session, author: User) -> None:
    other = make_user(db, email="other@example.com", handle="other", display_name="别人")
    character = characters_service.create_character(
        db,
        user_id=other.id,
        name="别人的角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    with pytest.raises(NotFound):
        characters_service.get_character(db, user_id=author.id, character_id=character.id)


def test_create_rejects_more_than_four_reference_assets(db: Session, author: User) -> None:
    assets = [_asset(db, author) for _ in range(5)]
    with pytest.raises(ValidationFailed):
        characters_service.create_character(
            db,
            user_id=author.id,
            name="太多素材",
            description=None,
            reference_asset_ids=[a.id for a in assets],
            voice_description=None,
        )


def test_create_rejects_someone_elses_asset(db: Session, author: User) -> None:
    other = make_user(db, email="other2@example.com", handle="other2", display_name="别人")
    asset = _asset(db, other)
    with pytest.raises(NotFound):
        characters_service.create_character(
            db,
            user_id=author.id,
            name="用了别人的素材",
            description=None,
            reference_asset_ids=[asset.id],
            voice_description=None,
        )


# ---- Reference asset persistence (regression coverage) --------------------


def test_reference_asset_writes_survive_a_fresh_reload_from_the_database(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="神秘女侦探",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    front = _asset(db, author)
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=character.id,
        asset_id=front.id,
        view=CharacterViewAngle.FRONT.value,
    )

    db.expire_all()
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.reference_asset_ids == [front.id]
    assert reloaded.reference_assets[0]["view"] == CharacterViewAngle.FRONT.value


def test_append_reference_asset_replaces_the_same_views_prior_image(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="神秘女侦探",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    first = _asset(db, author)
    second = _asset(db, author)
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=character.id,
        asset_id=first.id,
        view=CharacterViewAngle.FRONT.value,
    )
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=character.id,
        asset_id=second.id,
        view=CharacterViewAngle.FRONT.value,
    )

    db.expire_all()
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.reference_asset_ids == [second.id]


def test_update_reference_asset_view_survives_a_fresh_reload(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=asset.id
    )

    characters_service.update_reference_asset(
        db,
        user_id=author.id,
        character_id=character.id,
        asset_id=asset.id,
        view=CharacterViewAngle.SIDE.value,
        label="侧脸",
    )

    db.expire_all()
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.reference_assets[0]["view"] == CharacterViewAngle.SIDE.value
    assert reloaded.reference_assets[0]["label"] == "侧脸"


def test_update_reference_asset_rejects_an_unknown_asset_id(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    with pytest.raises(NotFound):
        characters_service.update_reference_asset(
            db, user_id=author.id, character_id=character.id, asset_id="ast_missing", view="general"
        )


def test_remove_reference_asset_survives_a_fresh_reload(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=asset.id
    )
    characters_service.remove_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=asset.id
    )

    db.expire_all()
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.reference_asset_ids == []


def test_update_character_description_survives_a_fresh_reload(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description="旧设定",
        reference_asset_ids=[],
        voice_description="旧声线",
    )
    characters_service.update_character(
        db,
        user_id=author.id,
        character_id=character.id,
        description="新设定",
        voice_description="新声线",
    )

    db.expire_all()
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.description == "新设定"
    assert reloaded.voice_description == "新声线"


def test_editing_a_published_character_withdraws_it_to_draft(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    characters_service.publish_character(
        db, user_id=author.id, character_id=character.id, portrait_consent=True
    )
    published = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert published.status == "pending_review"

    characters_service.update_character(
        db, user_id=author.id, character_id=character.id, name="改名"
    )
    reloaded = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert reloaded.status == "draft"
    assert reloaded.visibility == "private"


# ---- Publish / withdraw -----------------------------------------------------


def test_publish_requires_portrait_consent(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    with pytest.raises(ValidationFailed):
        characters_service.publish_character(
            db, user_id=author.id, character_id=character.id, portrait_consent=False
        )


def test_withdraw_returns_a_published_character_to_draft(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    characters_service.publish_character(
        db, user_id=author.id, character_id=character.id, portrait_consent=True
    )
    withdrawn = characters_service.withdraw_character(
        db, user_id=author.id, character_id=character.id
    )
    assert withdrawn.status == "draft"
    assert withdrawn.visibility == "private"


# ---- apply_character_refs (folded into a generation job's params) --------


def test_apply_character_refs_is_a_noop_without_character_ids(db: Session, author: User) -> None:
    params: dict[str, object] = {"reference_asset_ids": ["ast_existing"]}
    characters_service.apply_character_refs(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == ["ast_existing"]


def test_apply_character_refs_merges_reference_assets_and_voice_profiles(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description="低沉、克制",
    )
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=asset.id
    )

    params: dict[str, object] = {
        "character_ids": [character.id],
        "reference_asset_ids": ["ast_existing"],
    }
    characters_service.apply_character_refs(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == ["ast_existing", asset.id]
    profiles = params["extra"]["character_voice_profiles"]
    assert profiles == [
        {"character_id": character.id, "name": "林夏", "voice_description": "低沉、克制"}
    ]


def test_apply_character_refs_rejects_too_many_characters(db: Session, author: User) -> None:
    character_ids = [
        characters_service.create_character(
            db,
            user_id=author.id,
            name=f"角色{i}",
            description=None,
            reference_asset_ids=[],
            voice_description=None,
        ).id
        for i in range(5)
    ]
    params: dict[str, object] = {"character_ids": character_ids}
    with pytest.raises(ValidationFailed):
        characters_service.apply_character_refs(db, user_id=author.id, params=params)


def test_apply_character_refs_rejects_someone_elses_character(db: Session, author: User) -> None:
    other = make_user(db, email="other3@example.com", handle="other3", display_name="别人")
    character = characters_service.create_character(
        db,
        user_id=other.id,
        name="别人的角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    params: dict[str, object] = {"character_ids": [character.id]}
    with pytest.raises(NotFound):
        characters_service.apply_character_refs(db, user_id=author.id, params=params)


# ---- Series -----------------------------------------------------------------


def test_add_and_remove_character_from_series(db: Session, author: User) -> None:
    series = characters_service.create_series(
        db, user_id=author.id, title="深海霓虹", description=None, shortform_profile_key=None
    )
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    characters_service.add_character_to_series(
        db, user_id=author.id, series_id=series.id, character_id=character.id
    )
    detail = characters_service.get_series_detail(db, user_id=author.id, series_id=series.id)
    assert [c.id for c in detail.characters] == [character.id]

    characters_service.remove_character_from_series(
        db, user_id=author.id, series_id=series.id, character_id=character.id
    )
    detail = characters_service.get_series_detail(db, user_id=author.id, series_id=series.id)
    assert detail.characters == []


def test_deleting_a_character_removes_it_from_every_series_roster(
    db: Session, author: User
) -> None:
    series = characters_service.create_series(
        db, user_id=author.id, title="深海霓虹", description=None, shortform_profile_key=None
    )
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    characters_service.add_character_to_series(
        db, user_id=author.id, series_id=series.id, character_id=character.id
    )
    characters_service.delete_character(db, user_id=author.id, character_id=character.id)

    detail = characters_service.get_series_detail(db, user_id=author.id, series_id=series.id)
    assert detail.characters == []
    assert character.id not in detail.series.character_ids_json
