"""P2-6: a look's age stage is a closed vocabulary that reaches the sheet
and expression prompts, and presets are checked against the card kind."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.asset_variants import VariantPresets
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets import reference_resolver
from app.domain.image_assets.vocabulary import AGE_STAGE_PRESETS, AGE_STAGES
from app.domain.scenes import service as scenes_service
from app.models import User


def test_every_age_stage_has_a_preset() -> None:
    assert set(AGE_STAGES) == set(AGE_STAGE_PRESETS)
    with pytest.raises(ValidationError):
        VariantPresets.model_validate({"age_stage": "大学时期"})


def test_presets_must_fit_the_card_kind(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill
    with pytest.raises(ValidationFailed):
        av.create_variant(db, character, name="黄昏", presets={"lighting": "dusk"})
    with pytest.raises(ValidationFailed):
        av.create_variant(db, scene, name="少年", presets={"age_stage": "teen"})
    teen = av.create_variant(db, character, name="少年", presets={"age_stage": "teen"})
    with pytest.raises(ValidationFailed):
        av.update_variant(db, character, teen, presets={"age_stage": "teen", "weather": "rain"})
    assert teen.presets_json == {"age_stage": "teen"}


def test_the_target_look_carries_its_age_stage(db: Session, author: User) -> None:
    skill = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill
    teen = av.create_variant(db, skill, name="少年", presets={"age_stage": "teen"})
    params = {
        "prompt": "林夏",
        "asset_kind": "character",
        "target_character_id": skill.id,
        "target_variant_id": teen.id,
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    assert params["target_look"]["age_stage"] == "teen"


@pytest.mark.parametrize(
    "asset_pass", [pb.AssetPass.CHARACTER_SHEET, pb.AssetPass.CHARACTER_EXPRESSIONS]
)
def test_the_age_stage_reaches_the_prompt_and_keeps_the_identity(asset_pass) -> None:
    params = {
        "target_look": {"name": "少年", "age_stage": "teen"},
        "character_expressions": ["smile"],
    }
    prompt, negative = pb.compose(
        asset_pass, prompt="林夏", negative=None, params=params, has_reference=True
    )
    assert "年龄阶段：少年" in prompt
    assert "不要变成另一个人" in prompt
    assert "不同的人" in (negative or "")


def test_no_age_stage_adds_nothing() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"target_look": {"name": "婚礼"}},
    )
    assert "年龄阶段" not in prompt
