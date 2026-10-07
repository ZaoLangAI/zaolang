"""P3-2: where consistency verdicts live (`skill_asset_entries.consistency_json`)
and the `asset_consistency` config section."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.models import Asset, CreationSkill, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import AssetEntryStatus, MediaType
from app.platform_config import service as config_service
from app.platform_config.schemas import DEFAULT_CONFIGS, AssetConsistencyConfig
from app.presenters import asset_variants as presenters

# ---- config -------------------------------------------------------------------


def test_scoring_is_off_by_default_for_every_kind(db: Session) -> None:
    config = config_service.get_typed(db, "asset_consistency", AssetConsistencyConfig)
    assert config.mode == "off"
    assert config.kinds == ["character", "scene", "prop"]
    assert config.thresholds == {}
    assert (config.max_image_px, config.max_outputs_per_job) == (1024, 8)
    # No threshold anywhere means nothing is ever below.
    assert config.threshold_for("character", "identity_portrait") is None


def test_a_threshold_is_looked_up_by_entry_type_then_star() -> None:
    config = AssetConsistencyConfig.model_validate(
        {"thresholds": {"character": {"*": 70, "expression_sheet": 55}, "prop": {"master": 0}}}
    )
    assert config.threshold_for("character", "expression_sheet") == 55
    assert config.threshold_for("character", "character_sheet") == 70
    assert config.threshold_for("scene", "master") is None
    # 0 is a real threshold, not "unset".
    assert config.threshold_for("prop", "master") == 0
    assert config.threshold_for("prop", "view") is None


def test_shadow_with_thresholds_is_accepted_and_takes_effect(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["asset_consistency"])
    value.update(mode="shadow", kinds=["scene", "scene", "prop"], thresholds={"scene": {"*": 65}})
    config_service.set_value(db, "asset_consistency", value, actor_user_id=admin.id, note="t")

    config = config_service.get_typed(db, "asset_consistency", AssetConsistencyConfig)
    assert config.mode == "shadow"
    assert config.kinds == ["scene", "prop"]
    assert config.threshold_for("scene", "shot") == 65


@pytest.mark.parametrize(
    "patch",
    [
        {"mode": "on"},
        {"kinds": ["cover"]},
        {"thresholds": {"cover": {"*": 50}}},
        {"thresholds": {"character": {"master": 50}}},
        {"thresholds": {"scene": {"identity_portrait": 50}}},
        # A panorama is never scored, so a threshold for it is a mistake.
        {"thresholds": {"scene": {"panorama": 50}}},
        {"thresholds": {"prop": {"*": 101}}},
        {"thresholds": {"prop": {"*": -1}}},
        {"max_image_px": 256},
        {"max_image_px": 4096},
        {"max_outputs_per_job": 0},
        {"max_outputs_per_job": 9},
        {"unknown_field": True},
    ],
)
def test_invalid_values_are_refused(db: Session, admin: User, patch: dict[str, Any]) -> None:
    value = {**DEFAULT_CONFIGS["asset_consistency"], **patch}
    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "asset_consistency", value, actor_user_id=admin.id)


# ---- entries ------------------------------------------------------------------


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


def _character(db: Session, author: User) -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _verdict(*, below: bool) -> dict[str, Any]:
    return {
        "v": 1,
        "status": "scored",
        "score": 62 if below else 88,
        "threshold": 70,
        "below": below,
        "mode": "enforce",
        "demoted": below,
        "dimensions": {"face": 55, "hair": 80, "body": 70, "medium": 75},
        "issues": ["脸型偏长"],
        "rubric_version": 1,
        "owner_approved_at": None,
    }


def _scored_candidate(db: Session, author: User, skill: CreationSkill, *, below: bool):  # type: ignore[no-untyped-def]
    look = av.find_default(skill)
    assert look is not None
    av.file_generated(db, skill, look, asset_id=_asset(db, author).id, entry_type="character_sheet")
    entry = av.file_generated(
        db, skill, look, asset_id=_asset(db, author).id, entry_type="character_sheet"
    )
    assert entry.status == AssetEntryStatus.CANDIDATE
    entry.consistency_json = _verdict(below=below)
    db.flush()
    return entry


def test_approving_a_below_threshold_image_records_the_owners_call(
    db: Session, author: User
) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=True)
    before = entry.consistency_json

    av.approve_entry(db, skill, entry)

    db.refresh(entry)
    assert entry.consistency_json is not None
    assert entry.consistency_json["owner_approved_at"]
    assert entry.consistency_json["score"] == 62
    # Copied, not mutated in place (DM 11).
    assert before is not None and before["owner_approved_at"] is None


def test_approving_through_patch_records_it_too(db: Session, author: User) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=True)
    av.update_entry(db, skill, entry, status=AssetEntryStatus.APPROVED.value)
    assert entry.consistency_json and entry.consistency_json["owner_approved_at"]


def test_approving_through_the_flat_list_records_it_too(db: Session, author: User) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=True)
    approved = [e.asset_id for e in av.approved_entries(skill)]
    av.set_members(db, skill, [*approved, entry.asset_id])
    assert entry.consistency_json and entry.consistency_json["owner_approved_at"]


def test_approving_an_image_that_was_not_below_records_nothing(db: Session, author: User) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=False)
    av.approve_entry(db, skill, entry)
    assert entry.consistency_json and entry.consistency_json["owner_approved_at"] is None

    unscored = _scored_candidate(db, author, skill, below=False)
    unscored.consistency_json = None
    av.approve_entry(db, skill, unscored)
    assert unscored.consistency_json is None


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def test_no_projection_carries_the_score(db: Session, author: User) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=True)
    av.approve_entry(db, skill, entry)

    public = [
        view.model_dump(mode="json")
        for view in presenters.variant_views(db, skill, approved_only=True)
    ]
    owner = [view.model_dump(mode="json") for view in presenters.variant_views(db, skill)]
    for shape in (public, owner, av.project(skill)):
        text = _dump(shape)
        assert entry.asset_id in text
        assert "consistency" not in text
        assert "owner_approved_at" not in text


def test_an_adjusted_copy_starts_unscored(db: Session, author: User) -> None:
    """An adjust / derive files a new entry `copy_from_entry_id`-style; the
    source's verdict belongs to the source image only."""
    skill = _character(db, author)
    source = _scored_candidate(db, author, skill, below=True)
    av.approve_entry(db, skill, source)
    new_asset = _asset(db, author)

    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=skill.id,
        asset_id=new_asset.id,
        generated=True,
        copy_from_entry_id=source.id,
    )

    copy_entry = db.query(SkillAssetEntry).filter_by(asset_id=new_asset.id).one()
    assert copy_entry.entry_type == source.entry_type
    assert copy_entry.consistency_json is None


def test_moving_an_entry_keeps_its_score(db: Session, author: User) -> None:
    skill = _character(db, author)
    entry = _scored_candidate(db, author, skill, below=False)
    wedding = av.create_variant(db, skill, name="婚礼")
    av.update_entry(db, skill, entry, variant=wedding)
    db.refresh(entry)
    assert entry.variant_id == wedding.id
    assert entry.consistency_json and entry.consistency_json["score"] == 88
