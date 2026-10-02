"""The identity portrait (定妆照, P2-2): a clean head-and-shoulders face that
becomes the card's anchor, and that every sheet afterwards is drawn from."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.api.schemas.jobs import GenerationParams
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets import reference_resolver
from app.models import Asset, CreationSkill, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, AssetEntryType, MediaType


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


def _character(db: Session, author: User) -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _file(db: Session, author: User, skill: CreationSkill, **kwargs) -> SkillAssetEntry:
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=skill.id,
        asset_id=asset.id,
        view="front",
        generated=True,
        **kwargs,
    )
    return next(e for e in av.entries(skill) if e.asset_id == asset.id)


# ---- prompt -------------------------------------------------------------------


def test_the_portrait_pass_is_one_clean_head_and_shoulders_face() -> None:
    assert (
        pb.resolve_pass(
            {"character_portrait": True}, asset_kind="character", character_view="front"
        )
        is pb.AssetPass.IDENTITY_PORTRAIT
    )
    prompt, negative = pb.compose(
        pb.AssetPass.IDENTITY_PORTRAIT,
        prompt=f"林夏，短发，杏眼。{pb.CHARACTER_SHEET_LAYOUT_SUFFIX}",
        negative=None,
        params={"character_portrait": True},
    )
    assert prompt.startswith("林夏，短发，杏眼")
    assert "头肩构图" in prompt
    assert "三视图" not in prompt
    assert pb.CHARACTER_PHOTOREAL_MEDIUM in prompt
    assert "全身像" in (negative or "")


def test_a_sheet_drawn_from_the_portrait_locks_the_face_to_it() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={},
        has_reference=True,
        identity_reference=True,
    )
    assert prompt.startswith(pb.IDENTITY_LOCK_PREFIX)
    # 换装 already locks the face to reference 1: one sentence, not two.
    outfit, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"character_outfit_label": "婚礼"},
        has_reference=True,
        identity_reference=True,
    )
    assert pb.IDENTITY_LOCK_PREFIX not in outfit
    assert outfit.startswith("以参考图1中的人物为准")


def test_the_planner_cannot_pull_a_portrait_back_into_a_sheet() -> None:
    kept = pb.sanitize_enhancements(
        pb.AssetPass.IDENTITY_PORTRAIT, ["补充三视图与色板", "左眼角有一颗痣"], params={}
    )
    assert kept == ["左眼角有一颗痣"]


def test_polish_keeps_a_portrait_a_portrait() -> None:
    restored = copywriter.restore_identity_portrait_prompt(
        "林夏，短发。左侧为全身三视图，右侧为色板。"
    )
    assert "三视图" not in restored
    assert restored.endswith(copywriter.IDENTITY_PORTRAIT_SENTENCE)


@pytest.mark.parametrize(
    "extra",
    [
        {"asset_kind": "scene"},
        {"asset_kind": "character", "character_expressions": ["smile"]},
        {"asset_kind": "character", "character_outfit_label": "婚礼"},
        {"asset_kind": "character", "character_views": ["front", "side"]},
    ],
)
def test_a_portrait_job_is_a_single_front_character_image(extra: dict) -> None:
    with pytest.raises(ValidationError):
        GenerationParams.model_validate({"prompt": "林夏", "character_portrait": True, **extra})
    GenerationParams.model_validate(
        {"prompt": "林夏", "asset_kind": "character", "character_portrait": True}
    )


# ---- filing and anchor -----------------------------------------------------------


def test_an_approved_portrait_takes_the_anchor_from_the_sheet(db: Session, author: User) -> None:
    skill = _character(db, author)
    sheet = _file(db, author, skill)
    assert av.anchor(skill) is sheet

    wedding = av.create_variant(db, skill, name="婚礼")
    portrait = _file(db, author, skill, portrait=True, variant_id=wedding.id)

    assert portrait.entry_type == AssetEntryType.IDENTITY_PORTRAIT
    # One face for the whole card: always the default look.
    assert portrait.variant.is_default
    assert portrait.status == AssetEntryStatus.APPROVED
    assert av.anchor(skill) is portrait


def test_a_second_portrait_waits_as_a_candidate_and_approving_it_keeps_the_anchor_on_a_portrait(
    db: Session, author: User
) -> None:
    skill = _character(db, author)
    first = _file(db, author, skill, portrait=True)
    second = _file(db, author, skill, portrait=True)
    assert second.status == AssetEntryStatus.CANDIDATE
    assert av.anchor(skill) is first

    av.approve_entry(db, skill, second)
    assert av.anchor(skill) is second
    assert first.status == AssetEntryStatus.CANDIDATE


def test_a_hand_picked_portrait_anchor_is_not_overridden(db: Session, author: User) -> None:
    skill = _character(db, author)
    portrait = _file(db, author, skill, portrait=True)
    sheet = _file(db, author, skill)
    av.set_anchor(db, skill, sheet)
    # Re-approving or filing another portrait only takes over from a sheet;
    # the owner just chose the sheet, and the next portrait is a candidate.
    later = _file(db, author, skill, portrait=True)
    assert later.status == AssetEntryStatus.CANDIDATE
    assert av.anchor(skill) is sheet
    assert portrait.status == AssetEntryStatus.APPROVED


# ---- references ----------------------------------------------------------------


def test_a_target_card_sheet_job_borrows_the_portrait(db: Session, author: User) -> None:
    skill = _character(db, author)
    _file(db, author, skill)
    portrait = _file(db, author, skill, portrait=True)

    params = {"prompt": "林夏", "asset_kind": "character", "target_character_id": skill.id}
    reference_resolver.resolve(db, user_id=author.id, params=params)

    assert params["reference_asset_ids"] == [portrait.asset_id]
    assert av.is_identity_portrait(db, portrait.asset_id)
    assert params["reference_labels"][0]["label"].endswith("定妆照")


def test_no_portrait_means_no_borrowed_reference(db: Session, author: User) -> None:
    skill = _character(db, author)
    _file(db, author, skill)
    params = {"prompt": "林夏", "asset_kind": "character", "target_character_id": skill.id}
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert not params.get("reference_asset_ids")


def test_the_planning_node_locks_a_sheet_to_a_portrait_reference(db: Session, author: User) -> None:
    from app.models.enums import Operation
    from app.workflows.configs import AssetPlanningConfig
    from app.workflows.nodes import execute_asset_planning
    from app.workflows.types import WorkflowContext
    from tests.factories import make_job

    skill = _character(db, author)
    portrait = _file(db, author, skill, portrait=True)
    sheet_ref = _file(db, author, skill)

    def planned(reference: str) -> str:
        ctx = WorkflowContext(
            session=db,
            job=make_job(db, author, operation=Operation.TEXT_TO_IMAGE),
            prompt="林夏",
            params={
                "prompt": "林夏",
                "asset_kind": "character",
                "reference_asset_ids": [reference],
            },
        )
        execute_asset_planning(ctx, AssetPlanningConfig())
        return ctx.prompt

    assert planned(portrait.asset_id).startswith(pb.IDENTITY_LOCK_PREFIX)
    assert not planned(sheet_ref.asset_id).startswith(pb.IDENTITY_LOCK_PREFIX)
