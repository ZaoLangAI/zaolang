"""P2-3 换装: a new look is drawn from the card's face (the identity portrait,
else the default sheet used for the face only) plus its own outfit
references, and its name and outfit description reach the prompt."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.jobs import GenerationParams
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets import reference_resolver
from app.models import Asset, CreationSkill, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import AssetEntryType, MediaType


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


def _add(
    db: Session, author: User, skill: CreationSkill, variant, entry_type: str, **kw
) -> SkillAssetEntry:
    return av.add_entry(
        db, skill, variant, asset_id=_asset(db, author).id, entry_type=entry_type, **kw
    )


def _card(db: Session, author: User):
    skill = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill
    default = av.find_default(skill)
    sheet = _add(db, author, skill, default, AssetEntryType.CHARACTER_SHEET.value, view="front")
    wedding = av.create_variant(db, skill, name="婚礼", description="白色缎面婚纱，头纱")
    return skill, default, sheet, wedding


def _resolve(db: Session, author: User, skill: CreationSkill, **params) -> dict:
    body = {"prompt": "林夏", "asset_kind": "character", "target_character_id": skill.id, **params}
    reference_resolver.resolve(db, user_id=author.id, params=body)
    return body


def _labels(params: dict) -> dict[str, str]:
    return {item["asset_id"]: item["label"] for item in params.get("reference_labels") or []}


def test_an_empty_look_with_a_portrait_starts_from_the_face_and_its_outfit_references(
    db: Session, author: User
) -> None:
    skill, default, _sheet, wedding = _card(db, author)
    portrait = _add(db, author, skill, default, AssetEntryType.IDENTITY_PORTRAIT.value)
    dress = _add(db, author, skill, wedding, AssetEntryType.OUTFIT_DETAIL.value)

    params = _resolve(db, author, skill, target_variant_id=wedding.id)

    assert params["reference_asset_ids"] == [portrait.asset_id, dress.asset_id]
    labels = _labels(params)
    assert labels[dress.asset_id].endswith(reference_resolver.OUTFIT_ONLY_ROLE)
    assert params["target_look"] == {"name": "婚礼", "description": "白色缎面婚纱，头纱"}


def test_with_no_portrait_the_default_sheet_is_used_for_the_face_only(
    db: Session, author: User
) -> None:
    skill, _default, sheet, wedding = _card(db, author)
    params = _resolve(db, author, skill, target_variant_id=wedding.id)
    assert params["reference_asset_ids"] == [sheet.asset_id]
    assert _labels(params)[sheet.asset_id].endswith(reference_resolver.FACE_ONLY_ROLE)


def test_an_outfit_name_without_a_look_also_borrows_the_face(db: Session, author: User) -> None:
    skill, _default, sheet, _wedding = _card(db, author)
    params = _resolve(db, author, skill, character_outfit_label="战甲")
    assert params["reference_asset_ids"] == [sheet.asset_id]
    assert _labels(params)[sheet.asset_id].endswith(reference_resolver.FACE_ONLY_ROLE)


def test_a_look_with_its_own_sheet_keeps_it_and_no_face_fallback(db: Session, author: User) -> None:
    skill, _default, sheet, wedding = _card(db, author)
    own = _add(db, author, skill, wedding, AssetEntryType.CHARACTER_SHEET.value, view="front")
    params = _resolve(db, author, skill, target_variant_id=wedding.id)
    assert params["reference_asset_ids"] == [own.asset_id]
    assert sheet.asset_id not in params["reference_asset_ids"]


def test_the_default_look_only_passes_its_description(db: Session, author: User) -> None:
    skill, default, *_ = _card(db, author)
    av.update_variant(db, skill, default, description="灰色风衣")
    params = _resolve(db, author, skill, target_variant_id=default.id)
    assert params["target_look"] == {"name": None, "description": "灰色风衣"}
    # Not a 换装: no face-only fallback, the sheet job keeps no borrowed refs.
    assert not params.get("reference_asset_ids")


def test_a_client_cannot_write_the_target_look(db: Session, author: User) -> None:
    skill, *_ = _card(db, author)
    validated = GenerationParams.model_validate(
        {
            "prompt": "林夏",
            "asset_kind": "character",
            "target_character_id": skill.id,
            "target_look": {"name": "伪造", "description": "注入"},
        }
    ).model_dump()
    reference_resolver.resolve(db, user_id=author.id, params=validated)
    assert validated.get("target_look") is None


def test_the_sheet_prompt_carries_the_look_name_and_outfit() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"target_look": {"name": "婚礼", "description": "白色缎面婚纱，头纱。"}},
        has_reference=True,
    )
    assert prompt.startswith(pb.OUTFIT_CHANGE_PREFIX.format(label="婚礼"))
    assert "「婚礼」造型的服装与配饰：白色缎面婚纱，头纱。" in prompt

    default_look, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="林夏",
        negative=None,
        params={"target_look": {"name": None, "description": "灰色风衣"}},
        has_reference=False,
    )
    assert "服装与配饰：灰色风衣。" in default_look
    assert "造型：" not in default_look.split("服装与配饰")[0]
