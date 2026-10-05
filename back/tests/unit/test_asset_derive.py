"""P6: 调整修改 / 派生新属性图 — params validation, the source image as
reference 1 (and the scene still for `in_scene`), the edit / in-scene
prompt passes, derive plans, and write-back's auto edge."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.jobs import GenerationParams
from app.domain.asset_graph import derive
from app.domain.asset_graph import service as graph
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets import reference_resolver
from app.domain.scenes import service as scenes_service
from app.models import Asset, CreationSkill, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import ImageAssetKind, MediaType, Operation
from app.workflows.configs import AssetOutputLinkConfig
from app.workflows.nodes import execute_asset_output_link
from app.workflows.types import WorkflowContext
from tests.factories import make_job


def _asset(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _character(db: Session, owner: User, name: str = "林夏") -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=owner.id,
        name=name,
        description="真人写实影视短剧造型，年轻女性",
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _sheet(db: Session, skill: CreationSkill, variant=None) -> SkillAssetEntry:
    return av.add_entry(
        db,
        skill,
        variant or av.find_default(skill),
        asset_id=_owned_asset(db, skill),
        entry_type="character_sheet",
    )


def _owned_asset(db: Session, skill: CreationSkill) -> str:
    asset = Asset(
        owner_user_id=skill.owner_user_id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset.id


def _scene_with_master(db: Session, owner: User) -> CreationSkill:
    scene = scenes_service.create_scene(
        db, user_id=owner.id, name="码头", description=None, reference_asset_ids=[]
    ).skill
    av.add_entry(
        db, scene, av.find_default(scene), asset_id=_owned_asset(db, scene), entry_type="master"
    )
    return scene


# ---- params ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"prompt": "x", "asset_edit": True, "asset_kind": "character"},
        {"prompt": "x", "source_entry_id": "ske_1"},
        {
            "prompt": "x",
            "asset_kind": "scene",
            "source_entry_id": "s",
            "asset_output_mode": "in_scene",
        },
        {
            "prompt": "x",
            "asset_kind": "character",
            "source_entry_id": "s",
            "asset_edit": True,
            "character_portrait": True,
        },
        {"prompt": "x", "asset_kind": "scene", "asset_output_entry_type": "pose"},
    ],
)
def test_derive_params_are_validated(params: dict) -> None:
    with pytest.raises(ValidationError):
        GenerationParams.model_validate(params)


# ---- resolver --------------------------------------------------------------------


def test_the_source_image_is_reference_one(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    params = {
        "prompt": "把外套换成红色",
        "asset_kind": ImageAssetKind.CHARACTER.value,
        "target_character_id": skill.id,
        "target_variant_id": sheet.variant_id,
        "source_entry_id": sheet.id,
        "asset_edit": True,
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == [sheet.asset_id]
    assert params["reference_labels"][0]["label"].endswith(reference_resolver.SOURCE_ROLE)


def test_another_cards_image_is_a_422(db: Session, author: User) -> None:
    mine, theirs = _character(db, author), _character(db, author, name="周岩")
    foreign = _sheet(db, theirs)
    params = {
        "prompt": "x",
        "asset_kind": "character",
        "target_character_id": mine.id,
        "source_entry_id": foreign.id,
    }
    with pytest.raises(ValidationFailed):
        reference_resolver.resolve(db, user_id=author.id, params=params)


def test_in_scene_borrows_the_linked_scene_still(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    look = av.create_variant(db, skill, name="码头夜班")
    params = {
        "prompt": "林夏",
        "asset_kind": "character",
        "target_character_id": skill.id,
        "target_variant_id": look.id,
        "source_entry_id": sheet.id,
        "asset_output_mode": "in_scene",
    }
    with pytest.raises(ValidationFailed, match="还没有关联场景"):
        reference_resolver.resolve(db, user_id=author.id, params=dict(params))
    scene = _scene_with_master(db, author)
    av.set_scene_link(db, skill, look, scene_id=scene.id)
    reference_resolver.resolve(db, user_id=author.id, params=params)
    master = av.master_or_anchor(scene)
    assert master is not None
    assert params["reference_asset_ids"] == [sheet.asset_id, master.asset_id]
    labels = {item["asset_id"]: item["label"] for item in params["reference_labels"]}
    assert labels[master.asset_id].startswith("场景「码头」")
    assert labels[master.asset_id].endswith(reference_resolver.SCENE_ONLY_ROLE)


# ---- prompts ---------------------------------------------------------------------


def test_an_edit_changes_only_what_it_says() -> None:
    params = {"asset_edit": True, "asset_kind": "character"}
    asset_pass = pb.resolve_pass(params, asset_kind="character", character_view=None)
    assert asset_pass is pb.AssetPass.ASSET_EDIT
    prompt, negative = pb.compose(
        asset_pass, prompt="把外套换成红色。", negative=None, params=params
    )
    assert prompt.startswith("以参考图1为基础，只做以下修改：把外套换成红色。")
    assert "设定图" not in prompt.split("。")[0]
    assert "换成另一个人" in (negative or "")
    assert pb.sanitize_enhancements(asset_pass, ["加一顶帽子"], params=params) == []


def test_in_scene_places_the_character_without_a_sheet_layout() -> None:
    params = {
        "asset_output_mode": "in_scene",
        "target_look": {"name": "码头夜班", "state": "疲惫"},
    }
    asset_pass = pb.resolve_pass(params, asset_kind="character", character_view=None)
    assert asset_pass is pb.AssetPass.CHARACTER_IN_SCENE
    prompt, negative = pb.compose(asset_pass, prompt="林夏", negative=None, params=params)
    assert prompt.startswith(pb.IN_SCENE_PREFIX)
    assert "人物状态：疲惫" in prompt
    assert pb.CHARACTER_SHEET_LAYOUT_SUFFIX not in prompt
    assert "设定图版式" in (negative or "")


# ---- plans -----------------------------------------------------------------------


def test_an_adjust_targets_the_source_look(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    plan = derive.plan_adjust(
        db,
        user_id=author.id,
        kind="character",
        card_id=skill.id,
        entry_id=sheet.id,
        instruction=" 把外套换成红色 ",
    )
    assert plan.params["asset_edit"] is True
    assert plan.params["target_variant_id"] == sheet.variant_id
    assert plan.params["prompt"] == "把外套换成红色"
    assert plan.params["aspect_ratio"] == "16:9"
    GenerationParams.model_validate(plan.params)
    with pytest.raises(NotFound):
        derive.plan_adjust(
            db,
            user_id=author.id,
            kind="character",
            card_id=skill.id,
            entry_id="ske_x",
            instruction="x",
        )


def test_a_derive_into_a_new_look_previews_its_relations(db: Session, author: User) -> None:
    skill = _character(db, author)
    av.update_variant(db, skill, av.find_default(skill), presets={"age_stage": "youth"})
    sheet = _sheet(db, skill)
    plan = derive.plan_derive(
        db,
        user_id=author.id,
        kind="character",
        card_id=skill.id,
        entry_id=sheet.id,
        output="character_sheet",
        new_variant=derive.NewVariantDraft(
            name="老年", presets={"age_stage": "elderly"}, attributes={"state": "疲惫"}
        ),
    )
    assert plan.relations == ["age", "emotion"]
    assert "target_variant_id" not in plan.params
    # Nothing was written by the plan.
    assert [v.name for v in skill.asset_variants] == ["默认造型"]
    GenerationParams.model_validate(plan.params)


@pytest.mark.parametrize(
    ("output", "message"),
    [("identity_portrait", "默认造型"), ("in_scene", "关联场景"), ("master", "不支持")],
)
def test_derive_outputs_fit_their_target(
    db: Session, author: User, output: str, message: str
) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    look = av.create_variant(db, skill, name="婚礼")
    with pytest.raises(ValidationFailed, match=message):
        derive.plan_derive(
            db,
            user_id=author.id,
            kind="character",
            card_id=skill.id,
            entry_id=sheet.id,
            output=output,
            target_variant_id=look.id,
        )


def test_a_derive_needs_exactly_one_target(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    with pytest.raises(ValidationFailed, match="目标造型"):
        derive.plan_derive(
            db,
            user_id=author.id,
            kind="character",
            card_id=skill.id,
            entry_id=sheet.id,
            output="character_sheet",
        )
    with pytest.raises(ValidationFailed, match="同名"):
        derive.plan_derive(
            db,
            user_id=author.id,
            kind="character",
            card_id=skill.id,
            entry_id=sheet.id,
            output="character_sheet",
            new_variant=derive.NewVariantDraft(name="默认造型"),
        )


# ---- write-back ------------------------------------------------------------------


def _ctx(db: Session, author: User, params: dict) -> WorkflowContext:
    job = make_job(db, author, operation=Operation.TEXT_TO_IMAGE)
    return WorkflowContext(session=db, job=job, prompt="x", params={"prompt": "x", **params})


def test_an_adjust_is_filed_like_its_source_with_an_edit_edge(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "prompt": "把外套换成红色",
            "asset_kind": "character",
            "target_character_id": skill.id,
            "target_variant_id": sheet.variant_id,
            "source_entry_id": sheet.id,
            "asset_edit": True,
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    filed = next(e for e in av.entries(skill) if e.asset_id == output.id)
    assert filed.entry_type == "character_sheet"
    assert filed.variant_id == sheet.variant_id
    # The source still holds the slot, so the adjusted image is a candidate.
    assert filed.status == "candidate"
    (edge,) = graph.edges(db, skill, "entry")
    assert (edge.source_entry_id, edge.target_entry_id) == (sheet.id, filed.id)
    assert edge.relations_json == ["edit"]
    assert edge.label == "把外套换成红色"
    assert edge.origin == "auto" and edge.source_job_id == ctx.job.id


def test_an_in_scene_derive_is_filed_as_a_pose_with_a_scene_edge(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    look = av.create_variant(db, skill, name="码头夜班")
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "asset_kind": "character",
            "target_character_id": skill.id,
            "target_variant_id": look.id,
            "source_entry_id": sheet.id,
            "asset_output_mode": "in_scene",
            "asset_output_entry_type": "pose",
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    filed = next(e for e in look.entries if e.asset_id == output.id)
    assert filed.entry_type == "pose"
    (edge,) = graph.edges(db, skill, "entry")
    assert "scene" in edge.relations_json


def test_a_vanished_source_files_the_image_without_an_edge(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _sheet(db, skill)
    source_id = sheet.id
    av.remove_entry(db, skill, sheet)
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "asset_kind": "character",
            "target_character_id": skill.id,
            "source_entry_id": source_id,
            "asset_output_entry_type": "pose",
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert any(e.asset_id == output.id for e in av.entries(skill))
    assert graph.edges(db, skill) == []


def test_an_adjust_of_a_free_image_is_still_a_candidate_version(db: Session, author: User) -> None:
    """A pose has no slot, yet an adjust of it is a version waiting for 定稿,
    not a second approved pose (`file_generated(candidate=True)`)."""
    skill = _character(db, author)
    pose = av.add_entry(
        db, skill, av.find_default(skill), asset_id=_owned_asset(db, skill), entry_type="pose"
    )
    output = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        {
            "prompt": "抬起左手",
            "asset_kind": "character",
            "target_character_id": skill.id,
            "target_variant_id": pose.variant_id,
            "source_entry_id": pose.id,
            "asset_edit": True,
        },
    )
    ctx.state["asset_id"] = output.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())
    filed = next(e for e in av.entries(skill) if e.asset_id == output.id)
    assert (filed.entry_type, filed.status) == ("pose", "candidate")
