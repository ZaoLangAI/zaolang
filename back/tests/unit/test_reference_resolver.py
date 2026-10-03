"""P1-2: jobs pick, label and file images by look / scene variant
(`image_assets.reference_resolver`, write-back in `asset_output_link`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.jobs import GenerationParams
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.image_assets import reference_resolver
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, User
from app.models.base import new_id
from app.models.enums import (
    CreationSkillStatus,
    CreationSkillVisibility,
    ImageAssetKind,
    MediaType,
    Operation,
)
from app.workflows.configs import AssetOutputLinkConfig
from app.workflows.nodes import execute_asset_output_link
from app.workflows.types import WorkflowContext
from tests.conftest import make_user
from tests.factories import make_job


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="d" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _character_with_looks(db: Session, author: User):
    """林夏: default look (front sheet + side view), 婚礼 look (front sheet)."""
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    daily_front, daily_side, wedding_front = (_asset(db, author) for _ in range(3))
    for asset, view, label in (
        (daily_front, "front", None),
        (daily_side, "side", None),
        (wedding_front, "front", "婚礼"),
    ):
        characters_service.append_reference_asset(
            db,
            user_id=author.id,
            character_id=character.id,
            asset_id=asset.id,
            view=view,
            label=label,
        )
    wedding = av.find_by_name(character.skill, "婚礼")
    assert wedding is not None
    return character, wedding, (daily_front, daily_side, wedding_front)


# ---- selection & defaults ------------------------------------------------------


def test_a_look_id_alone_picks_that_looks_default_subset(db: Session, author: User) -> None:
    character, wedding, (daily_front, _, wedding_front) = _character_with_looks(db, author)
    params: dict[str, object] = {
        "character_ids": [character.id],
        "character_ref_selection": [{"character_id": character.id, "variant_id": wedding.id}],
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    # The default look's sheet (the anchor) shows the 日常 outfit — it stays out.
    assert params["reference_asset_ids"] == [wedding_front.id]
    assert params["reference_labels"] == [
        {"asset_id": wedding_front.id, "label": "角色「林夏」·婚礼·设定图"}
    ]
    assert daily_front.id not in params["reference_asset_ids"]  # type: ignore[operator]


def test_no_selection_uses_the_default_look_front_then_side(db: Session, author: User) -> None:
    character, _, (daily_front, daily_side, _) = _character_with_looks(db, author)
    params: dict[str, object] = {"character_ids": [character.id]}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [daily_front.id, daily_side.id]
    assert [item["label"] for item in params["reference_labels"]] == [  # type: ignore[union-attr]
        "角色「林夏」·设定图",
        "角色「林夏」·侧面",
    ]


def test_images_must_belong_to_the_named_look(db: Session, author: User) -> None:
    character, wedding, (daily_front, _, _) = _character_with_looks(db, author)
    params: dict[str, object] = {
        "character_ids": [character.id],
        "character_ref_selection": [
            {"character_id": character.id, "variant_id": wedding.id, "asset_ids": [daily_front.id]}
        ],
    }
    with pytest.raises(ValidationFailed):
        reference_resolver.resolve(db, user_id=author.id, params=params)


def test_a_foreign_look_id_is_rejected(db: Session, author: User) -> None:
    character, _, _ = _character_with_looks(db, author)
    params: dict[str, object] = {
        "character_ids": [character.id],
        "character_ref_selection": [{"character_id": character.id, "variant_id": "skv_nope"}],
    }
    with pytest.raises(ValidationFailed):
        reference_resolver.resolve(db, user_id=author.id, params=params)


def test_an_identity_portrait_anchor_joins_any_look(db: Session, author: User) -> None:
    character, wedding, (_, _, wedding_front) = _character_with_looks(db, author)
    default = av.find_default(character.skill)
    assert default is not None
    portrait = av.add_entry(
        db,
        character.skill,
        default,
        asset_id=_asset(db, author).id,
        entry_type="identity_portrait",
    )
    av.set_anchor(db, character.skill, portrait)
    picked = characters_service.default_reference_asset_ids(character, variant_id=wedding.id)
    assert picked == [portrait.asset_id, wedding_front.id]


def test_a_scene_variant_without_its_own_master_falls_back_to_the_anchor(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )
    master = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=master.id, view="establishing"
    )
    empty = av.create_variant(db, scene.skill, name="战损·中")
    params: dict[str, object] = {
        "scene_ids": [scene.id],
        "scene_ref_selection": [{"scene_id": scene.id, "variant_id": empty.id}],
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [master.id]


def test_a_scene_image_with_no_reference_borrows_its_targets_master(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )
    master = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=master.id, view="establishing"
    )
    night = av.create_variant(db, scene.skill, name="夜", presets={"lighting": "night_interior"})
    night_plate = _asset(db, author)
    av.add_entry(db, scene.skill, night, asset_id=night_plate.id, entry_type="master")

    cell: dict[str, object] = {
        "asset_kind": "scene",
        "target_scene_id": scene.id,
        "scene_lighting": "dusk",
    }
    reference_resolver.resolve(db, user_id=author.id, params=cell)
    assert cell["reference_asset_ids"] == [master.id]

    into_night: dict[str, object] = {
        "asset_kind": "scene",
        "target_scene_id": scene.id,
        "target_variant_id": night.id,
    }
    reference_resolver.resolve(db, user_id=author.id, params=into_night)
    assert into_night["reference_asset_ids"] == [night_plate.id]

    upload = _asset(db, author)
    explicit: dict[str, object] = {
        "asset_kind": "scene",
        "target_scene_id": scene.id,
        "reference_asset_ids": [upload.id],
    }
    reference_resolver.resolve(db, user_id=author.id, params=explicit)
    assert explicit["reference_asset_ids"] == [upload.id]


def test_an_expression_sheet_borrows_the_target_looks_sheet(db: Session, author: User) -> None:
    character, wedding, (_, _, wedding_front) = _character_with_looks(db, author)
    params: dict[str, object] = {
        "character_expressions": ["smile"],
        "target_character_id": character.id,
        "target_variant_id": wedding.id,
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [wedding_front.id]


def test_selection_schema_needs_a_look_or_images() -> None:
    with pytest.raises(ValidationError):
        GenerationParams(
            prompt="x", character_ids=["chr_a"], character_ref_selection=[{"character_id": "chr_a"}]
        )
    params = GenerationParams(
        prompt="x",
        character_ids=["chr_a"],
        character_ref_selection=[{"character_id": "chr_a", "variant_id": "skv_1"}],
    )
    assert params.character_ref_selection is not None
    assert params.character_ref_selection[0].asset_ids is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_kind": ImageAssetKind.GENERAL, "target_variant_id": "skv_1"},
        {
            "asset_kind": ImageAssetKind.CHARACTER,
            "target_variant_id": "skv_1",
            "character_outfit_label": "婚礼",
        },
        {
            "asset_kind": ImageAssetKind.SCENE,
            "target_variant_id": "skv_1",
            "scene_variants": [{"lighting": "day"}, {"lighting": "dusk"}],
        },
    ],
)
def test_target_variant_id_is_scoped(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        GenerationParams(prompt="x", **overrides)


# ---- write-back targeting --------------------------------------------------------


def _ctx(db: Session, author: User, params: dict) -> WorkflowContext:
    job = make_job(db, author, operation=Operation.TEXT_TO_IMAGE)
    return WorkflowContext(session=db, job=job, prompt="x", params={"prompt": "x", **params})


def test_write_back_files_into_the_target_look_with_its_job(db: Session, author: User) -> None:
    character, wedding, _ = _character_with_looks(db, author)
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
            "target_variant_id": wedding.id,
            "character_expressions": ["smirk", "shy"],
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    entry = next(e for e in wedding.entries if e.asset_id == output.id)
    assert entry.entry_type == "expression_sheet"
    assert entry.expressions_json == ["smirk", "shy"]
    assert entry.source_job_id == ctx.job.id


def test_write_back_files_a_scene_preset_image_as_that_variants_master(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "asset_kind": ImageAssetKind.SCENE.value,
            "target_scene_id": scene.id,
            "scene_lighting": "dusk",
            "scene_weather": "rain",
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    variant = next(v for v in scene.skill.asset_variants if not v.is_default)
    assert variant.name == "黄昏 / 雨"
    assert variant.presets_json == {"lighting": "dusk", "weather": "rain"}
    assert [(e.asset_id, e.entry_type) for e in variant.entries] == [(output.id, "master")]

    # A second image with the same presets lands in the same variant as a shot.
    again = _asset(db, author)
    ctx2 = _ctx(db, author, {**ctx.params, "prompt": "x"})
    ctx2.state["asset_id"] = again.id
    execute_asset_output_link(ctx2, AssetOutputLinkConfig())
    assert [e.entry_type for e in variant.entries] == ["master", "shot"]


def test_a_stale_target_variant_falls_back_to_the_default(db: Session, author: User) -> None:
    character, _, _ = _character_with_looks(db, author)
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
            "target_variant_id": "skv_gone",
            "character_views": ["side"],
        },
    )
    ctx.state["asset_outputs"] = [{"asset_id": output.id, "view": "side"}]
    execute_asset_output_link(ctx, AssetOutputLinkConfig())
    default = av.find_default(character.skill)
    assert default is not None
    assert output.id in {e.asset_id for e in default.entries}


# ---- marketplace -----------------------------------------------------------------


def test_an_unlocked_cards_approved_images_are_usable_references(db: Session, author: User) -> None:
    character, _, (daily_front, _, _) = _character_with_looks(db, author)
    skill: CreationSkill = character.skill
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()
    buyer = make_user(db, email="buyer@example.com", handle="buyer", display_name="买家")
    image = db.get(Asset, daily_front.id)
    assert image is not None

    assert skill_library_service.asset_is_usable_skill_reference(
        db, asset=image, viewer_id=buyer.id
    )
    skill.access_credits = 50
    db.flush()
    assert not skill_library_service.asset_is_usable_skill_reference(
        db, asset=image, viewer_id=buyer.id
    )
