"""AC-7: the scene panorama slot — one per variant, scene cards only, and
never a reference (default subset, angled ranking, anchor, master)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.scenes import service as scenes_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, AssetEntryType, MediaType


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="c" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _scene(db: Session, author: User):
    return scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )


def _panorama(db: Session, author: User, scene, variant=None):
    return av.file_generated(
        db,
        scene.skill,
        variant or av.find_default(scene.skill),
        asset_id=_asset(db, author).id,
        entry_type=AssetEntryType.PANORAMA.value,
    )


def test_one_panorama_slot_per_variant(db: Session, author: User) -> None:
    scene = _scene(db, author)
    dusk = av.create_variant(db, scene.skill, name="黄昏")
    first = _panorama(db, author, scene)
    second = _panorama(db, author, scene)
    elsewhere = _panorama(db, author, scene, dusk)
    assert first.status == AssetEntryStatus.APPROVED
    assert second.status == AssetEntryStatus.CANDIDATE
    assert elsewhere.status == AssetEntryStatus.APPROVED

    av.approve_entry(db, scene.skill, second)
    assert first.status == AssetEntryStatus.CANDIDATE
    assert elsewhere.status == AssetEntryStatus.APPROVED


def test_only_scene_cards_take_a_panorama(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description="短发",
        reference_asset_ids=[],
        voice_description=None,
    )
    with pytest.raises(ValidationFailed):
        av.add_entry(
            db,
            character.skill,
            av.find_default(character.skill),
            asset_id=_asset(db, author).id,
            entry_type=AssetEntryType.PANORAMA.value,
        )


def test_a_panorama_is_never_a_default_reference(db: Session, author: User) -> None:
    scene = _scene(db, author)
    variant = av.find_default(scene.skill)
    panorama = _panorama(db, author, scene)
    # A panorama alone: nothing to send, and it never becomes the master.
    scenes_service._promote_master(db, scene.skill)
    assert panorama.entry_type == AssetEntryType.PANORAMA
    assert av.anchor(scene.skill) is None
    assert av.default_subset(scene.skill) == []
    assert av.master_or_anchor(scene.skill) is None

    master = av.add_entry(
        db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="master"
    )
    shot = av.add_entry(db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="shot")
    assert av.default_subset(scene.skill) == [master.asset_id, shot.asset_id]
    close = av.ReferenceHints(shot="close")
    assert panorama.asset_id not in av.default_subset(scene.skill, variant, hints=close)


def test_the_angled_ranking_skips_a_panorama(db: Session, author: User) -> None:
    scene = _scene(db, author)
    variant = av.find_default(scene.skill)
    panorama = _panorama(db, author, scene)
    reverse = av.add_entry(
        db,
        scene.skill,
        variant,
        asset_id=_asset(db, author).id,
        entry_type="shot",
        camera={"azimuth": 180},
    )
    hints = av.ReferenceHints(side="back")
    picked = av.default_subset(scene.skill, hints=hints)
    assert picked[0] == reverse.asset_id
    assert panorama.asset_id not in picked


def test_a_panorama_cannot_be_the_anchor(db: Session, author: User) -> None:
    scene = _scene(db, author)
    panorama = _panorama(db, author, scene)
    with pytest.raises(ValidationFailed):
        av.set_anchor(db, scene.skill, panorama)


def test_the_legend_calls_it_a_panorama(db: Session, author: User) -> None:
    scene = _scene(db, author)
    assert av.entry_label(scene.skill, _panorama(db, author, scene)) == "场景「客厅」·全景"
