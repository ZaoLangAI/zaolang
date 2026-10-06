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


# ---- the panorama job (GenerationParams, prompt pass, references) ----------


def test_a_panorama_job_is_a_single_2_to_1_scene_image() -> None:
    from pydantic import ValidationError

    from app.api.schemas.jobs import GenerationParams

    params = GenerationParams(
        prompt="老式客厅",
        asset_kind="scene",
        target_scene_id="sk_1",
        scene_panorama=True,
        aspect_ratio="16:9",
    )
    assert params.aspect_ratio == "2:1"
    for bad in (
        {"asset_kind": "character", "target_character_id": "sk_1"},
        {"asset_kind": "scene"},  # no target
        {
            "asset_kind": "scene",
            "target_scene_id": "sk_1",
            "scene_variants": [{"lighting": "day"}, {"lighting": "dusk"}],
        },
        {
            "asset_kind": "scene",
            "target_scene_id": "sk_1",
            "camera_poses": [{"azimuth": 90}],
            "reference_asset_ids": ["ast_1"],
        },
        {"asset_kind": "scene", "target_scene_id": "sk_1", "source_entry_id": "ske_1"},
    ):
        with pytest.raises(ValidationError):
            GenerationParams(prompt="客厅", scene_panorama=True, **bad)
    # Presets still apply: a panorama at dusk.
    dusk = GenerationParams(
        prompt="客厅",
        asset_kind="scene",
        target_scene_id="sk_1",
        scene_panorama=True,
        scene_lighting="dusk",
    )
    assert dusk.scene_lighting == "dusk"


def test_the_panorama_pass_asks_for_a_seamless_equirectangular_plate() -> None:
    from app.domain.image_assets import prompt_builder
    from app.domain.image_assets.prompt_builder import AssetPass

    params = {"asset_kind": "scene", "scene_panorama": True}
    asset_pass = prompt_builder.resolve_pass(params, asset_kind="scene", character_view=None)
    assert asset_pass is AssetPass.SCENE_PANORAMA
    prompt, negative = prompt_builder.compose(
        asset_pass, prompt="老式客厅，木地板", negative=None, params=params
    )
    assert prompt.startswith("老式客厅，木地板")
    for phrase in ("360°", "等距柱状投影", "2:1", "无缝衔接", "地平线", "不出现人物"):
        assert phrase in prompt
    assert negative and "人物" in negative and "鱼眼" in negative

    with_master, _ = prompt_builder.compose(
        asset_pass,
        prompt="老式客厅",
        negative=None,
        params={**params, "scene_lighting": "dusk"},
        has_reference=True,
    )
    assert with_master.startswith(prompt_builder.SCENE_PANORAMA_REFERENCE_PREFIX)
    assert "黄昏" in with_master or "夕阳" in with_master

    kept = prompt_builder.sanitize_enhancements(
        asset_pass, ["墙上挂钟", "近景特写桌面", "三视图"], params=params
    )
    assert kept == ["墙上挂钟"]


def test_a_panorama_borrows_only_the_variant_master(db: Session, author: User) -> None:
    from app.domain.image_assets import reference_resolver

    scene = _scene(db, author)
    variant = av.find_default(scene.skill)
    base = {"prompt": "客厅", "asset_kind": "scene", "target_scene_id": scene.id}

    shot = av.add_entry(db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="shot")
    params = {**base, "scene_panorama": True}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert not params.get("reference_asset_ids")  # a shot is not borrowed

    master = av.add_entry(
        db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="master"
    )
    params = {**base, "scene_panorama": True}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [master.asset_id]

    ordinary = dict(base)
    reference_resolver.resolve(db, user_id=author.id, params=ordinary)
    assert shot.asset_id in ordinary["reference_asset_ids"]
