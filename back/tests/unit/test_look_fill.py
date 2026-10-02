"""P2-4 补齐缺失: what a look is missing and the waves of jobs that fill it."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import fill
from app.domain.characters import service as characters_service
from app.domain.image_assets import reference_resolver
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, AssetEntryType, MediaType


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="c" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _character(db: Session, author: User):
    return characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description="短发，杏眼",
        reference_asset_ids=[],
        voice_description=None,
    )


def _add(db, author, character, variant, entry_type, **kw):
    return av.add_entry(
        db, character.skill, variant, asset_id=_asset(db, author).id, entry_type=entry_type, **kw
    )


def test_an_empty_card_fills_in_three_waves(db: Session, author: User) -> None:
    character = _character(db, author)
    look = av.find_default(character.skill)
    assert set(fill.gaps(character, look).values()) == {"missing"}

    lines = fill.plan(character, look)

    assert [(line.wave, line.slots) for line in lines] == [
        (1, ("portrait",)),
        (2, ("front", "side", "back")),
        (3, ("expressions",)),
    ]
    assert lines[0].params["character_portrait"] is True
    assert lines[1].params["character_views"] == ["front", "side", "back"]
    assert lines[1].output_count == 3
    assert lines[2].params["character_expressions"] == list(fill.DEFAULT_FILL_EXPRESSIONS)
    assert all(line.params["target_character_id"] == character.id for line in lines)
    assert lines[0].params["prompt"] == "林夏。短发，杏眼"


def test_only_missing_slots_are_planned_and_candidates_are_left_alone(
    db: Session, author: User
) -> None:
    character = _character(db, author)
    look = av.find_default(character.skill)
    _add(db, author, character, look, AssetEntryType.IDENTITY_PORTRAIT.value)
    _add(db, author, character, look, AssetEntryType.CHARACTER_SHEET.value, view="front")
    _add(
        db,
        author,
        character,
        look,
        AssetEntryType.VIEW.value,
        view="side",
        status=AssetEntryStatus.CANDIDATE.value,
    )

    status = fill.gaps(character, look)
    assert status == {
        "portrait": "present",
        "front": "present",
        "side": "candidate",
        "back": "missing",
        "expressions": "missing",
    }
    lines = fill.plan(character, look, expressions=["smile", "shy"])
    assert [(line.wave, line.slots) for line in lines] == [(1, ("back",)), (2, ("expressions",))]
    assert lines[1].params["character_expressions"] == ["smile", "shy"]


def test_slots_restrict_the_plan_and_a_new_look_carries_its_outfit(
    db: Session, author: User
) -> None:
    character = _character(db, author)
    wedding = av.create_variant(db, character.skill, name="婚礼", description="白色婚纱。")
    lines = fill.plan(character, wedding, slots=["front"])
    assert [line.slots for line in lines] == [("front",)]
    assert lines[0].params["target_variant_id"] == wedding.id
    assert lines[0].params["prompt"] == "林夏。短发，杏眼。白色婚纱"


def test_a_side_back_job_draws_from_the_looks_front_sheet(db: Session, author: User) -> None:
    character = _character(db, author)
    look = av.find_default(character.skill)
    portrait = _add(db, author, character, look, AssetEntryType.IDENTITY_PORTRAIT.value)
    sheet = _add(db, author, character, look, AssetEntryType.CHARACTER_SHEET.value, view="front")
    params = {
        "prompt": "林夏",
        "asset_kind": "character",
        "target_character_id": character.id,
        "target_variant_id": look.id,
        "character_views": ["side", "back"],
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [sheet.asset_id, portrait.asset_id]
