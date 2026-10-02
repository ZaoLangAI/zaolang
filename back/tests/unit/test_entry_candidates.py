"""Candidate / approved entries (P2-1): a generated image never replaces an
approved one in its slot — it waits beside it as a candidate until the owner
approves it, and nobody but the owner's editor sees candidates."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.scenes import service as scenes_service
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


def _generated(db: Session, author: User, skill: CreationSkill, **kwargs) -> SkillAssetEntry:
    asset = _asset(db, author)
    characters_service.append_reference_asset(
        db,
        user_id=author.id,
        character_id=skill.id,
        asset_id=asset.id,
        source_job_id=new_id("job"),
        generated=True,
        **kwargs,
    )
    return next(e for e in av.entries(skill) if e.asset_id == asset.id)


def test_an_empty_slot_is_approved_and_a_filled_one_gets_a_candidate(
    db: Session, author: User
) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    second = _generated(db, author, skill, view="front")

    assert first.status == AssetEntryStatus.APPROVED
    assert first.is_anchor
    assert second.status == AssetEntryStatus.CANDIDATE
    assert second.entry_type == AssetEntryType.CHARACTER_SHEET
    # Nothing was replaced: both images are on the card.
    assert {e.asset_id for e in av.entries(skill)} == {first.asset_id, second.asset_id}


def test_slots_are_per_view_and_per_expression_set(db: Session, author: User) -> None:
    skill = _character(db, author)
    _generated(db, author, skill, view="front")
    side = _generated(db, author, skill, view="side")
    back = _generated(db, author, skill, view="back")
    smile = _generated(db, author, skill, expressions=["smile", "anger"])
    other_set = _generated(db, author, skill, expressions=["sad"])
    same_set = _generated(db, author, skill, expressions=["anger", "smile"])

    assert side.status == back.status == AssetEntryStatus.APPROVED
    assert smile.status == other_set.status == AssetEntryStatus.APPROVED
    assert same_set.status == AssetEntryStatus.CANDIDATE


def test_a_look_has_its_own_slots(db: Session, author: User) -> None:
    skill = _character(db, author)
    _generated(db, author, skill, view="front")
    wedding = av.create_variant(db, skill, name="婚礼")
    wedding_sheet = _generated(db, author, skill, view="front", variant_id=wedding.id)
    assert wedding_sheet.status == AssetEntryStatus.APPROVED


def test_a_manual_upload_still_replaces_the_slot(db: Session, author: User) -> None:
    """Only a job's write-back keeps candidates; the owner filing an image by
    hand means "this is the sheet"."""
    skill = _character(db, author)
    _generated(db, author, skill, view="front")
    manual = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=skill.id, asset_id=manual.id, view="front"
    )
    sheets = [e for e in av.entries(skill) if e.entry_type == AssetEntryType.CHARACTER_SHEET]
    assert [e.asset_id for e in sheets] == [manual.id]


def test_approving_swaps_the_slot_and_moves_the_anchor(db: Session, author: User) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    second = _generated(db, author, skill, view="front")

    av.approve_entry(db, skill, second)

    assert second.status == AssetEntryStatus.APPROVED
    assert first.status == AssetEntryStatus.CANDIDATE
    assert av.anchor(skill) is second
    assert [item["asset_id"] for item in av.project(skill)] == [second.asset_id]


def test_candidates_stay_out_of_every_shared_read(db: Session, author: User) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    candidate = _generated(db, author, skill, view="front")

    assert [item["asset_id"] for item in av.project(skill)] == [first.asset_id]
    assert av.asset_ids(skill) == [first.asset_id]
    assert candidate.asset_id not in av.default_subset(skill)


def test_a_candidate_cannot_be_the_anchor_and_the_anchor_cannot_become_one(
    db: Session, author: User
) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    candidate = _generated(db, author, skill, view="front")

    with pytest.raises(ValidationFailed):
        av.set_anchor(db, skill, candidate)
    with pytest.raises(ValidationFailed):
        av.update_entry(db, skill, first, status=AssetEntryStatus.CANDIDATE.value)


def test_patching_status_to_approved_goes_through_the_swap(db: Session, author: User) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    second = _generated(db, author, skill, view="front")

    av.update_entry(db, skill, second, status=AssetEntryStatus.APPROVED.value)

    assert first.status == AssetEntryStatus.CANDIDATE
    assert av.anchor(skill) is second


def test_caps_count_approved_entries_only(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Candidates are kept until the owner deletes them, so they must never
    stop a write-back; a full look turns a new generated image into a
    candidate instead of skipping it."""
    monkeypatch.setattr(av, "MAX_ENTRIES_PER_VARIANT", 2)
    skill = _character(db, author)
    _generated(db, author, skill, view="front")
    for _ in range(3):
        _generated(db, author, skill, view="front")
    _generated(db, author, skill, view="side")
    back = _generated(db, author, skill, view="back")

    assert back.status == AssetEntryStatus.CANDIDATE
    approved = [e for e in av.entries(skill) if e.status == AssetEntryStatus.APPROVED]
    assert len(approved) == 2
    assert len(av.entries(skill)) == 6
    with pytest.raises(ValidationFailed):
        av.approve_entry(db, skill, back)


def test_the_flat_edit_keeps_candidates(db: Session, author: User) -> None:
    skill = _character(db, author)
    first = _generated(db, author, skill, view="front")
    candidate = _generated(db, author, skill, view="front")

    characters_service.update_character(
        db,
        user_id=author.id,
        character_id=skill.id,
        reference_asset_ids=[item["asset_id"] for item in av.project(skill)],
    )

    assert {e.asset_id for e in av.entries(skill)} == {first.asset_id, candidate.asset_id}


def test_a_generated_scene_master_waits_beside_the_approved_one(db: Session, author: User) -> None:
    skill = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill
    dusk = av.create_variant(db, skill, name="黄昏", presets={"lighting": "dusk"})
    plates = []
    for _ in range(2):
        asset = _asset(db, author)
        scenes_service.append_reference_asset(
            db,
            user_id=author.id,
            scene_id=skill.id,
            asset_id=asset.id,
            view="establishing",
            variant_id=dusk.id,
            generated=True,
        )
        plates.append(next(e for e in dusk.entries if e.asset_id == asset.id))

    assert [(e.entry_type, e.status) for e in plates] == [
        (AssetEntryType.MASTER, AssetEntryStatus.APPROVED),
        (AssetEntryType.MASTER, AssetEntryStatus.CANDIDATE),
    ]
    av.approve_entry(db, skill, plates[1])
    assert [(e.entry_type, e.status) for e in plates] == [
        (AssetEntryType.MASTER, AssetEntryStatus.CANDIDATE),
        (AssetEntryType.MASTER, AssetEntryStatus.APPROVED),
    ]
