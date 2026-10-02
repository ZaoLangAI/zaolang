"""Looks / variants as tables (`app.domain.asset_variants.service`): the
constraints the database enforces, the P0-shaped projection and its JSON
mirror, and the guards around them."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.media import service as media_service
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, SkillAssetEntry, SkillAssetVariant, User
from app.models.base import new_id
from app.models.enums import AssetEntryType, MediaType


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


def _character(db: Session, author: User, name: str = "林夏") -> CreationSkill:
    view = characters_service.create_character(
        db,
        user_id=author.id,
        name=name,
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    return view.skill


def test_a_new_card_gets_exactly_one_default_look(db: Session, author: User) -> None:
    skill = _character(db, author)
    looks = av.variants(skill)
    assert [(v.name, v.is_default, v.kind) for v in looks] == [("默认造型", True, "look")]
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill
    assert [(v.name, v.kind) for v in av.variants(scene)] == [("主场景", "scene_variant")]


def test_look_names_are_unique_and_the_default_cannot_be_deleted(db: Session, author: User) -> None:
    skill = _character(db, author)
    wedding = av.create_variant(db, skill, name="婚礼", description="白色婚纱")
    with pytest.raises(ValidationFailed):
        av.create_variant(db, skill, name=" 婚礼 ")
    with pytest.raises(ValidationFailed):
        av.delete_variant(db, skill, av.find_default(skill))  # type: ignore[arg-type]

    av.update_variant(db, skill, wedding, make_default=True)
    assert av.find_default(skill) is wedding
    defaults = db.scalars(
        select(SkillAssetVariant).where(
            SkillAssetVariant.skill_id == skill.id, SkillAssetVariant.is_default
        )
    ).all()
    assert len(defaults) == 1


def test_the_look_count_is_capped(db: Session, author: User) -> None:
    skill = _character(db, author)
    for index in range(av.MAX_VARIANTS_PER_SKILL - 1):
        av.create_variant(db, skill, name=f"造型{index}")
    with pytest.raises(ValidationFailed):
        av.create_variant(db, skill, name="一个太多")


def test_one_anchor_per_card(db: Session, author: User) -> None:
    skill = _character(db, author)
    default = av.find_default(skill)
    assert default is not None
    first = av.add_entry(
        db, skill, default, asset_id=_asset(db, author).id, entry_type="character_sheet"
    )
    second = av.add_entry(
        db, skill, default, asset_id=_asset(db, author).id, entry_type="identity_portrait"
    )
    av.set_anchor(db, skill, first)
    av.set_anchor(db, skill, second)
    anchors = db.scalars(
        select(SkillAssetEntry).where(
            SkillAssetEntry.skill_id == skill.id, SkillAssetEntry.is_anchor
        )
    ).all()
    assert [a.id for a in anchors] == [second.id]


def test_entry_types_must_fit_the_card(db: Session, author: User) -> None:
    skill = _character(db, author)
    default = av.find_default(skill)
    assert default is not None
    with pytest.raises(ValidationFailed):
        av.add_entry(db, skill, default, asset_id=_asset(db, author).id, entry_type="master")


def test_an_entry_cannot_point_at_another_cards_look(db: Session, author: User) -> None:
    mine = _character(db, author)
    other = _character(db, author, name="周野")
    foreign_look = av.find_default(other)
    assert foreign_look is not None
    db.add(
        SkillAssetEntry(
            variant_id=foreign_look.id,
            skill_id=mine.id,
            asset_id=_asset(db, author).id,
            entry_type="other",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_the_projection_is_computed_and_nothing_is_stored_in_params_json(
    db: Session, author: User
) -> None:
    character = characters_service.get_character(
        db, user_id=author.id, character_id=_character(db, author).id
    )
    sheet = _asset(db, author)
    wedding = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=sheet.id, view="front"
    )
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=character.id,
        asset_id=wedding.id,
        view="front",
        label="婚礼",
    )
    db.expire_all()
    skill = db.get(CreationSkill, character.id)
    assert skill is not None
    # P2-8: the tables are the only copy — no JSON mirror is written.
    assert "reference_assets" not in skill.params_json["character"]
    projected = characters_service.CharacterView(skill).reference_assets
    assert [(m["asset_id"], m["view"], m["label"]) for m in projected] == [
        (sheet.id, "front", None),
        (wedding.id, "front", "婚礼"),
    ]
    assert projected[0]["is_anchor"] is True
    assert projected[1]["entry_type"] == AssetEntryType.CHARACTER_SHEET


def test_moderation_texts_cover_look_names_and_labels(db: Session, author: User) -> None:
    skill = _character(db, author)
    look = av.create_variant(db, skill, name="战甲", description="银色铠甲")
    av.add_entry(
        db,
        skill,
        look,
        asset_id=_asset(db, author).id,
        entry_type="expression_sheet",
        label="表情·冷笑",
    )
    texts = av.moderation_texts(skill)
    assert {"战甲", "银色铠甲", "表情·冷笑"} <= set(texts)


def test_publish_moderates_look_text(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill
    av.create_variant(db, skill, name="战损·中")
    seen: list[str] = []

    def capture(session, *, texts, **kwargs):  # type: ignore[no-untyped-def]
        seen.extend(t for t in texts if t)

    monkeypatch.setattr(skill_library_service, "assert_allowed", capture)
    skill_library_service.publish(db, skill=skill, actor_user_id=author.id)
    assert "战损·中" in seen


def test_deleting_the_card_or_the_asset_cascades(db: Session, author: User) -> None:
    skill = _character(db, author)
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=skill.id, asset_id=asset.id, view="front"
    )
    db.delete(asset)
    db.flush()
    db.expire_all()
    assert (
        db.scalars(select(SkillAssetEntry).where(SkillAssetEntry.skill_id == skill.id)).all() == []
    )

    skill_library_service.delete(db, skill=skill, actor_user_id=author.id)
    db.flush()
    assert (
        db.scalars(select(SkillAssetVariant).where(SkillAssetVariant.skill_id == skill.id)).all()
        == []
    )


def test_a_cards_image_is_not_deleted_with_a_work(db: Session, author: User) -> None:
    skill = _character(db, author)
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=skill.id, asset_id=asset.id, view="front"
    )
    assert media_service._is_shared(db, asset.id, except_work_id="wrk_none")


# ---- migration mapping (`20261001_1317_skill_asset_variants.py`) ----------


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[2] / "alembic" / "versions" / "20261001_1317_skill_asset_variants.py"
    )
    spec = importlib.util.spec_from_file_location("skill_asset_variants_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_maps_character_views_labels_and_the_anchor() -> None:
    names, entries = _migration().plan_entries(
        "character",
        [
            {"asset_id": "a", "view": "side"},
            {"asset_id": "b", "view": "front"},
            {"asset_id": "c", "view": "front", "label": "婚礼"},
            {"asset_id": "d", "view": "general", "label": "表情·冷笑"},
            {"asset_id": "e", "view": "general"},
            {"asset_id": "b", "view": "front"},
            {"view": "front"},
        ],
    )
    assert names == ["默认造型", "婚礼"]
    assert [(e["variant"], e["asset_id"], e["entry_type"], e["view"]) for e in entries] == [
        ("默认造型", "a", "view", "side"),
        ("默认造型", "b", "character_sheet", "front"),
        ("婚礼", "c", "character_sheet", "front"),
        ("默认造型", "d", "expression_sheet", None),
        ("默认造型", "e", "other", None),
    ]
    assert [e["asset_id"] for e in entries if e["is_anchor"]] == ["b"]
    assert next(e for e in entries if e["asset_id"] == "d")["label"] == "表情·冷笑"


def test_migration_picks_the_scene_master_like_p0() -> None:
    migration = _migration()
    _, with_establishing = migration.plan_entries(
        "scene_asset",
        [
            {"asset_id": "a", "view": "scene"},
            {"asset_id": "b", "view": "establishing"},
            {"asset_id": "c", "view": "detail"},
        ],
    )
    assert [(e["asset_id"], e["entry_type"], e["view"]) for e in with_establishing] == [
        ("a", "shot", None),
        ("b", "master", None),
        ("c", "shot", "detail"),
    ]
    assert [e["asset_id"] for e in with_establishing if e["is_anchor"]] == ["b"]

    names, first_unlabelled = migration.plan_entries(
        "scene_asset",
        [{"asset_id": "x", "view": "scene", "label": "黄昏"}, {"asset_id": "y", "view": "scene"}],
    )
    assert names == ["主场景", "黄昏"]
    assert [e["asset_id"] for e in first_unlabelled if e["is_anchor"]] == ["y"]
