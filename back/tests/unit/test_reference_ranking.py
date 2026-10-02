"""P2-7: a card's default references are ranked for the shot — a close-up
leads with the face, a wide shot with the turnaround — within the same caps,
and never override an explicit pick."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.image_assets import reference_resolver
from app.domain.scenes import service as scenes_service
from app.models import Asset, CreationSkill, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import AssetEntryType, MediaType


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _add(
    db: Session, author: User, skill: CreationSkill, entry_type: str, **kwargs
) -> SkillAssetEntry:
    variant = kwargs.pop("variant", None) or av.find_default(skill)
    return av.add_entry(
        db, skill, variant, asset_id=_asset(db, author).id, entry_type=entry_type, **kwargs
    )


def _character(db: Session, author: User):
    skill = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill
    sheet = _add(db, author, skill, AssetEntryType.CHARACTER_SHEET.value, view="front")
    side = _add(db, author, skill, AssetEntryType.VIEW.value, view="side")
    back = _add(db, author, skill, AssetEntryType.VIEW.value, view="back")
    portrait = _add(db, author, skill, AssetEntryType.IDENTITY_PORTRAIT.value)
    angry = _add(
        db, author, skill, AssetEntryType.EXPRESSION_SHEET.value, expressions=["anger", "shock"]
    )
    av.set_anchor(db, skill, sheet)
    return skill, sheet, side, back, portrait, angry


def test_without_hints_the_default_order_is_unchanged(db: Session, author: User) -> None:
    skill, sheet, side, back, *_ = _character(db, author)
    assert av.default_subset(skill) == [sheet.asset_id, side.asset_id, back.asset_id]


def test_a_close_up_leads_with_the_face_and_the_matching_expression(
    db: Session, author: User
) -> None:
    skill, sheet, _side, _back, portrait, angry = _character(db, author)
    hints = av.ReferenceHints(shot="close", emotion="anger")
    assert av.default_subset(skill, hints=hints) == [
        portrait.asset_id,
        angry.asset_id,
        sheet.asset_id,
    ]
    # An expression the card has no sheet for adds nothing.
    calm = av.ReferenceHints(shot="close", emotion="smile")
    assert av.default_subset(skill, hints=calm)[:2] == [portrait.asset_id, sheet.asset_id]


def test_a_medium_shot_with_an_emotion_adds_the_expression_after_the_anchor(
    db: Session, author: User
) -> None:
    skill, sheet, side, _back, _portrait, angry = _character(db, author)
    hints = av.ReferenceHints(shot="medium", emotion="anger")
    assert av.default_subset(skill, hints=hints) == [sheet.asset_id, angry.asset_id, side.asset_id]


def test_a_wide_shot_leads_with_the_turnaround(db: Session, author: User) -> None:
    skill, sheet, side, back, portrait, _ = _character(db, author)
    av.set_anchor(db, skill, portrait)
    hints = av.ReferenceHints(shot="wide", emotion="anger")
    assert av.default_subset(skill, hints=hints) == [sheet.asset_id, side.asset_id, back.asset_id]


def test_a_close_scene_shot_leads_with_detail_shots(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill
    master = _add(db, author, scene, AssetEntryType.MASTER.value)
    detail = _add(db, author, scene, AssetEntryType.SHOT.value, view="detail")
    assert av.default_subset(scene) == [master.asset_id, detail.asset_id]
    close = av.ReferenceHints(shot="extreme_close")
    assert av.default_subset(scene, hints=close) == [detail.asset_id, master.asset_id]


def test_the_resolver_reads_the_shot_from_the_prompts_camera_line(
    db: Session, author: User
) -> None:
    skill, sheet, _side, _back, portrait, angry = _character(db, author)
    params = {
        "prompt": "客厅\n动作：林夏转身\n镜头：近景，缓慢推进\n台词：林夏：你来了",
        "character_ids": [skill.id],
        "reference_emotion": "anger",
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [portrait.asset_id, angry.asset_id, sheet.asset_id]


def test_close_up_words_outside_the_camera_line_do_not_count(db: Session, author: User) -> None:
    skill, sheet, side, back, *_ = _character(db, author)
    params = {"prompt": "林夏的特写照片挂在墙上", "character_ids": [skill.id]}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [sheet.asset_id, side.asset_id, back.asset_id]


def test_an_explicit_pick_is_never_reordered(db: Session, author: User) -> None:
    skill, sheet, side, *_ = _character(db, author)
    params = {
        "prompt": "x",
        "character_ids": [skill.id],
        "character_ref_selection": [
            {"character_id": skill.id, "asset_ids": [side.asset_id, sheet.asset_id]}
        ],
        "reference_shot_size": "close",
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [side.asset_id, sheet.asset_id]
