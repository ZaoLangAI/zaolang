"""AC-2: camera-pose slots, the orbit prompt passes and `camera_poses`
validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.jobs import GenerationParams
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.image_assets import prompt_builder
from app.domain.image_assets.prompt_builder import AssetPass
from app.domain.scenes import service as scenes_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, AssetEntryType, MediaType

SIDE = {"azimuth": 90, "elevation": 0, "distance": "medium"}


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


def _character(db: Session, author: User):
    return characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description="短发",
        reference_asset_ids=[],
        voice_description=None,
    )


def test_a_posed_side_view_competes_with_an_old_side_view(db: Session, author: User) -> None:
    character = _character(db, author)
    look = av.find_default(character.skill)
    old = av.add_entry(
        db, character.skill, look, asset_id=_asset(db, author).id, entry_type="view", view="side"
    )
    new = av.file_generated(
        db,
        character.skill,
        look,
        asset_id=_asset(db, author).id,
        entry_type="view",
        view="side",
        camera=SIDE,
    )
    assert old.status == AssetEntryStatus.APPROVED
    assert new.status == AssetEntryStatus.CANDIDATE
    other_side = av.file_generated(
        db,
        character.skill,
        look,
        asset_id=_asset(db, author).id,
        entry_type="view",
        view="side",
        camera={"azimuth": 270},
    )
    assert other_side.status == AssetEntryStatus.APPROVED
    assert other_side.camera_json == {"azimuth": 270, "elevation": 0, "distance": "medium"}

    av.approve_entry(db, character.skill, new)
    assert old.status == AssetEntryStatus.CANDIDATE
    assert other_side.status == AssetEntryStatus.APPROVED
    assert av.entry_label(character.skill, other_side) == "角色「林夏」·左侧 270°·平视·中景"
    projected = {item["asset_id"]: item for item in av.project(character.skill)}
    assert projected[other_side.asset_id]["camera"]["azimuth"] == 270


def test_posed_scene_shots_are_slots_and_unposed_ones_accumulate(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )
    variant = av.find_default(scene.skill)
    reverse = {"azimuth": 180}
    first = av.file_generated(
        db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="shot", camera=reverse
    )
    second = av.file_generated(
        db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="shot", camera=reverse
    )
    loose = [
        av.file_generated(
            db, scene.skill, variant, asset_id=_asset(db, author).id, entry_type="shot"
        )
        for _ in range(2)
    ]
    assert first.status == AssetEntryStatus.APPROVED
    assert second.status == AssetEntryStatus.CANDIDATE
    assert all(e.status == AssetEntryStatus.APPROVED for e in loose)


def test_entry_pose_reads_stored_pose_then_view() -> None:
    from app.models import SkillAssetEntry

    sheet = SkillAssetEntry(entry_type=AssetEntryType.CHARACTER_SHEET.value)
    back = SkillAssetEntry(entry_type=AssetEntryType.VIEW.value, view="back")
    posed = SkillAssetEntry(entry_type=AssetEntryType.SHOT.value, camera_json={"azimuth": 45})
    portrait = SkillAssetEntry(entry_type=AssetEntryType.IDENTITY_PORTRAIT.value)
    assert av.entry_pose(sheet).azimuth == 0
    assert av.entry_pose(back).azimuth == 180
    assert av.entry_pose(posed).azimuth == 45
    assert av.entry_pose(portrait) is None
    with pytest.raises(Exception, match="机位无效"):
        av.check_camera({"azimuth": "x"})


def test_orbit_passes_resolve_and_compose() -> None:
    params = {"asset_kind": "scene", "camera_pose": {"azimuth": 180}}
    assert (
        prompt_builder.resolve_pass(params, asset_kind="scene", character_view=None)
        is AssetPass.CAMERA_ORBIT
    )
    prompt, negative = prompt_builder.compose(
        AssetPass.CAMERA_ORBIT, prompt="客厅。木地板", negative=None, params=params
    )
    assert "保持建筑结构" in prompt and "拍摄主体背面" in prompt and "主体：客厅。木地板" in prompt
    assert negative and "多视角拼接" in negative

    character = {"asset_kind": "character", "camera_pose": {"azimuth": 270, "elevation": 30}}
    prompt, _ = prompt_builder.compose(
        AssetPass.CAMERA_ORBIT, prompt="林夏", negative=None, params=character
    )
    assert "向左旋转90度" in prompt and "略高机位俯拍" in prompt
    # An old side/back completion pass keeps its fixed prompt.
    assert (
        prompt_builder.resolve_pass(character, asset_kind="character", character_view="side")
        is AssetPass.CHARACTER_COMPLETION
    )
    extract = {"asset_kind": "character", "orbit_front_extract": True}
    assert (
        prompt_builder.resolve_pass(extract, asset_kind="character", character_view="front")
        is AssetPass.SHEET_FRONT_FIGURE
    )
    assert prompt_builder.sanitize_enhancements(AssetPass.CAMERA_ORBIT, ["夕阳"], params={}) == []


def test_camera_poses_validation() -> None:
    ok = GenerationParams.model_validate(
        {
            "asset_kind": "scene",
            "source_entry_id": "ske_1",
            "camera_poses": [{"azimuth": 180}, {"azimuth": 90, "elevation": 30}],
        }
    )
    assert ok.camera_poses is not None and len(ok.camera_poses) == 2
    bad = [
        {"asset_kind": "general", "reference_asset_ids": ["a"], "camera_poses": [{"azimuth": 0}]},
        {"asset_kind": "scene", "camera_poses": [{"azimuth": 0}]},
        {
            "asset_kind": "scene",
            "source_entry_id": "s",
            "camera_poses": [{"azimuth": 90}, {"azimuth": 100}],
        },
        {
            "asset_kind": "character",
            "source_entry_id": "s",
            "character_portrait": True,
            "camera_poses": [{"azimuth": 90}],
        },
        {
            "asset_kind": "character",
            "source_entry_id": "s",
            "camera_from_sheet": True,
            "camera_poses": [{"azimuth": 90}],
        },
        {"asset_kind": "character", "camera_from_sheet": True},
        {"asset_kind": "scene", "source_entry_id": "s", "camera_poses": [{"azimuth": 360}]},
    ]
    for params in bad:
        with pytest.raises(ValidationError):
            GenerationParams.model_validate(params)


def test_a_client_camera_pose_in_extra_is_dropped(db: Session, author: User) -> None:
    from app.domain.image_assets import reference_resolver

    params = {"prompt": "x", "extra": {"camera_pose": {"azimuth": 90}, "voice": "alloy"}}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["extra"] == {"voice": "alloy"}
