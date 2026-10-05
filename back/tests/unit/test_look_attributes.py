"""P3: a look's free-text attributes, period and scene link — validated per
card kind, carried into `target_look` and written into the sheet /
expression prompts."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets import reference_resolver
from app.domain.image_assets.vocabulary import CHARACTER_PERIOD_PRESETS, PERIOD_PRESETS
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill, User


def _character(db: Session, owner: User, name: str = "林夏") -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=owner.id,
        name=name,
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _scene(db: Session, owner: User, name: str = "便利店") -> CreationSkill:
    return scenes_service.create_scene(
        db, user_id=owner.id, name=name, description=None, reference_asset_ids=[]
    ).skill


def test_every_scene_period_has_a_character_period() -> None:
    assert set(CHARACTER_PERIOD_PRESETS) == set(PERIOD_PRESETS)


def test_attributes_are_trimmed_and_blanks_dropped(db: Session, author: User) -> None:
    skill = _character(db, author)
    look = av.create_variant(
        db,
        skill,
        name="战损",
        presets={"age_stage": "youth", "period": "republic"},
        attributes={
            "outfit": " 破旧长衫 ",
            "state": "",
            "custom": [{"key": "身份", "value": "卧底"}, {"key": "", "value": ""}],
        },
    )
    assert look.presets_json == {"age_stage": "youth", "period": "republic"}
    assert look.attributes_json == {
        "outfit": "破旧长衫",
        "custom": [{"key": "身份", "value": "卧底"}],
    }


@pytest.mark.parametrize(
    "attributes",
    [
        {"outfit": "超" * 21},
        {"custom": [{"key": "身份", "value": ""}]},
        {"custom": [{"key": "身份", "value": "甲"}, {"key": "身份", "value": "乙"}]},
        {"custom": [{"key": f"k{i}", "value": "v"} for i in range(9)]},
        {"lighting": "dusk"},
    ],
)
def test_bad_attributes_are_a_422(db: Session, author: User, attributes: dict) -> None:
    skill = _character(db, author)
    with pytest.raises(ValidationFailed):
        av.create_variant(db, skill, name="坏属性", attributes=attributes)


def test_a_scene_variant_takes_only_custom_attributes(db: Session, author: User) -> None:
    scene = _scene(db, author)
    with pytest.raises(ValidationFailed):
        av.create_variant(db, scene, name="黄昏", attributes={"outfit": "西装"})
    variant = av.create_variant(
        db, scene, name="黄昏", attributes={"custom": [{"key": "氛围", "value": "压抑"}]}
    )
    assert variant.attributes_json["custom"] == [{"key": "氛围", "value": "压抑"}]


def test_a_scene_link_must_be_the_owners_scene(db: Session, author: User, remixer: User) -> None:
    skill = _character(db, author)
    look = av.find_default(skill)
    assert look is not None
    theirs = _scene(db, remixer)
    with pytest.raises(ValidationFailed):
        av.set_scene_link(db, skill, look, scene_id=theirs.id)
    mine = _scene(db, author)
    other = _scene(db, author, name="仓库")
    foreign_variant = av.find_default(other)
    assert foreign_variant is not None
    with pytest.raises(ValidationFailed):
        av.set_scene_link(db, skill, look, scene_id=mine.id, scene_variant_id=foreign_variant.id)
    with pytest.raises(ValidationFailed):
        # A character card is not a scene.
        av.set_scene_link(db, skill, look, scene_id=_character(db, author, "周岩").id)
    av.set_scene_link(db, skill, look, scene_id=mine.id)
    assert look.scene_skill_id == mine.id


def test_deleting_the_scene_clears_the_link(db: Session, author: User) -> None:
    skill = _character(db, author)
    look = av.create_variant(db, skill, name="便利店夜班")
    scene = _scene(db, author)
    av.set_scene_link(db, skill, look, scene_id=scene.id)
    db.flush()
    scenes_service.delete_scene(db, user_id=author.id, scene_id=scene.id)
    db.flush()
    db.refresh(look)
    assert look.scene_skill_id is None


def test_attribute_text_is_moderated(db: Session, author: User) -> None:
    skill = _character(db, author)
    av.create_variant(
        db,
        skill,
        name="卧底",
        attributes={"state": "满身是血", "custom": [{"key": "身份", "value": "卧底"}]},
    )
    texts = av.moderation_texts(skill)
    assert "满身是血" in texts
    assert "身份：卧底" in texts


def test_the_target_look_carries_every_attribute(db: Session, author: User) -> None:
    skill = _character(db, author)
    look = av.find_default(skill)
    assert look is not None
    # A default look with only attributes still writes `target_look`.
    av.update_variant(
        db,
        skill,
        look,
        presets={"period": "1980s"},
        attributes={"state": "疲惫", "custom": [{"key": "职业", "value": "工人"}]},
    )
    params = {
        "prompt": "林夏",
        "asset_kind": "character",
        "target_character_id": skill.id,
        "target_variant_id": look.id,
    }
    reference_resolver.resolve(db, user_id=author.id, params=params)
    target = params["target_look"]
    assert target["name"] is None
    assert target["period"] == "1980s"
    assert target["state"] == "疲惫"
    assert target["custom"] == [{"key": "职业", "value": "工人"}]


@pytest.mark.parametrize(
    "asset_pass", [pb.AssetPass.CHARACTER_SHEET, pb.AssetPass.CHARACTER_EXPRESSIONS]
)
def test_attributes_reach_the_prompt(asset_pass: pb.AssetPass) -> None:
    params = {
        "target_look": {
            "name": "战损",
            "period": "republic",
            "state": "满身尘土",
            "scene_note": "雨夜码头",
            "custom": [{"key": "身份", "value": "卧底"}],
        },
        "character_expressions": ["smile"],
    }
    prompt, negative = pb.compose(
        asset_pass, prompt="林夏", negative=None, params=params, has_reference=True
    )
    assert "时代背景：民国时期" in prompt
    assert "人物状态：满身尘土" in prompt
    assert "所处情境：雨夜码头" in prompt
    assert "其他设定：身份：卧底" in prompt
    assert "现代潮牌" in (negative or "")


def test_the_outfit_attribute_names_the_outfit_change() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"target_look": {"name": "第三幕", "outfit": "婚纱"}},
        has_reference=True,
    )
    assert "「婚纱」造型" in prompt
    assert "第三幕" not in prompt


def test_no_attributes_add_nothing() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"target_look": {"name": "婚礼"}},
    )
    for marker in ("时代背景", "人物状态", "所处情境", "其他设定"):
        assert marker not in prompt
