"""调整修改 / 派生新属性图 (P6): the job parameters for generating from one
of a card's own images, in the page instead of the image studio.

- **adjust**: redraw the image changing only what the instruction says
  (`asset_edit`). Filed like the source: same look, type, view.
- **derive**: a new image for another look — an existing one, or a new
  look created from a draft (attributes, scene link) — drawn from the source
  image as reference 1. The output type is picked: a sheet, the identity
  portrait (default look only), an expression grid, or the character placed
  in its look's scene (`in_scene`); for a scene, a master or a shot.

- **orbit** (多机位, AC-2): the source image re-drawn from other camera
  poses, one image per pose, filed as each pose's slot of the same look /
  variant (`plan_orbit`).

Plans are pure reads: nothing is created until the API submits (which also
writes the new look and the look-level auto edge in the same transaction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph_service
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.characters.fill import DEFAULT_FILL_EXPRESSIONS
from app.domain.errors import NotFound, ValidationFailed
from app.domain.image_assets import camera as camera_vocab
from app.domain.image_assets.vocabulary import MAX_CHARACTER_EXPRESSIONS
from app.domain.props import service as props_service
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill, SkillAssetEntry, SkillAssetVariant
from app.models.enums import AssetEntryType, AssetVariantKind, ImageAssetKind

CharacterOutput = Literal["character_sheet", "identity_portrait", "expression_sheet", "in_scene"]
SceneOutput = Literal["master", "shot"]
DeriveOutput = Literal[
    "character_sheet", "identity_portrait", "expression_sheet", "in_scene", "master", "shot"
]
CHARACTER_OUTPUTS: frozenset[str] = frozenset(
    {"character_sheet", "identity_portrait", "expression_sheet", "in_scene"}
)
SCENE_OUTPUTS: frozenset[str] = frozenset({"master", "shot"})
# A prop's derive draws its hero plate or a detail shot (AC-4).
PROP_OUTPUTS = SCENE_OUTPUTS

MAX_INSTRUCTION_LEN = 500

# The canvas shape each output reads best in, unless the caller picks one.
DEFAULT_ASPECT: dict[str, str] = {
    AssetEntryType.CHARACTER_SHEET: "16:9",
    AssetEntryType.IDENTITY_PORTRAIT: "3:4",
    AssetEntryType.EXPRESSION_SHEET: "1:1",
    AssetEntryType.POSE: "3:4",
    AssetEntryType.MASTER: "16:9",
    AssetEntryType.SHOT: "16:9",
    "in_scene": "16:9",
}


@dataclass(frozen=True, slots=True)
class NewVariantDraft:
    name: str
    description: str | None = None
    presets: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    scene_id: str | None = None
    scene_variant_id: str | None = None


@dataclass(slots=True)
class Plan:
    skill: CreationSkill
    source: SkillAssetEntry
    params: dict[str, Any]
    # Look-level relations source look → target look (derive only).
    relations: list[str]
    target: SkillAssetVariant | None = None
    new_variant: NewVariantDraft | None = None


def _card(
    session: Session, *, user_id: str, kind: str, card_id: str
) -> tuple[CreationSkill, str, str | None]:
    if kind == "character":
        character = characters_service.get_character(session, user_id=user_id, character_id=card_id)
        return character.skill, character.name, character.description
    if kind == "prop":
        prop = props_service.get_prop(session, user_id=user_id, prop_id=card_id)
        return prop.skill, prop.name, prop.description
    scene = scenes_service.get_scene(session, user_id=user_id, scene_id=card_id)
    return scene.skill, scene.name, scene.description


def _source(skill: CreationSkill, entry_id: str) -> SkillAssetEntry:
    entry = av.find_entry(skill, entry_id)
    if entry is None:
        raise NotFound("参考图不存在。")
    if av.is_panorama(entry):
        # A 2:1 equirectangular still redrawn as an ordinary image would be
        # neither a panorama nor a usable plate; cut a posed shot first.
        raise ValidationFailed(
            "全景图不能直接调整或派生，请先截取一个机位。", fields={"entry_id": "全景图"}
        )
    return entry


_BASE_KIND = {
    "character": (ImageAssetKind.CHARACTER, "target_character_id"),
    "scene": (ImageAssetKind.SCENE, "target_scene_id"),
    "prop": (ImageAssetKind.PROP, "target_prop_id"),
}


def _base(kind: str, skill: CreationSkill, name: str) -> dict[str, Any]:
    asset_kind, target_key = _BASE_KIND[kind]
    return {
        "asset_kind": asset_kind.value,
        target_key: skill.id,
        "subject_name_hint": name[:60],
    }


def _sentence(*parts: str | None) -> str:
    return "。".join(p.strip().rstrip("。．.") for p in parts if p and p.strip())


def plan_adjust(
    session: Session,
    *,
    user_id: str,
    kind: str,
    card_id: str,
    entry_id: str,
    instruction: str,
    aspect_ratio: str | None = None,
) -> Plan:
    skill, name, _description = _card(session, user_id=user_id, kind=kind, card_id=card_id)
    source = _source(skill, entry_id)
    text = instruction.strip()
    if not text:
        raise ValidationFailed("请写明要调整的内容。", fields={"instruction": "不能为空"})
    params = {
        **_base(kind, skill, name),
        "prompt": text[:MAX_INSTRUCTION_LEN],
        "source_entry_id": source.id,
        "asset_edit": True,
        "target_variant_id": source.variant_id,
        "aspect_ratio": aspect_ratio or DEFAULT_ASPECT.get(source.entry_type, "1:1"),
    }
    return Plan(skill=skill, source=source, params=params, relations=[])


def _draft_variant(skill: CreationSkill, draft: NewVariantDraft) -> SkillAssetVariant:
    """A transient look / variant (never added to the session) so a dry run
    can diff and prompt against a look that does not exist yet."""
    if av.find_by_name(skill, draft.name.strip()) is not None:
        raise ValidationFailed("已有同名的造型/变体。", fields={"new_variant.name": "名称已存在"})
    presets, attributes = av.check_variant_fields(
        skill, presets=draft.presets, attributes=draft.attributes
    )
    return SkillAssetVariant(
        kind={
            "character": AssetVariantKind.LOOK,
            "scene": AssetVariantKind.SCENE_VARIANT,
            "prop": AssetVariantKind.PROP_VARIANT,
        }[av.card_kind(skill)].value,
        name=draft.name.strip(),
        description=(draft.description or "").strip() or None,
        presets_json=presets,
        attributes_json=attributes,
        is_default=False,
        scene_skill_id=draft.scene_id,
        scene_variant_id=draft.scene_variant_id,
    )


def plan_derive(
    session: Session,
    *,
    user_id: str,
    kind: str,
    card_id: str,
    entry_id: str,
    output: str,
    target_variant_id: str | None = None,
    new_variant: NewVariantDraft | None = None,
    prompt_extra: str | None = None,
    expressions: list[str] | None = None,
    aspect_ratio: str | None = None,
) -> Plan:
    skill, name, description = _card(session, user_id=user_id, kind=kind, card_id=card_id)
    source = _source(skill, entry_id)
    character = kind == "character"
    if output not in (CHARACTER_OUTPUTS if character else SCENE_OUTPUTS):  # props: as scenes
        raise ValidationFailed("这张卡片不支持这种输出。", fields={"output": "不支持"})
    if (target_variant_id is None) == (new_variant is None):
        raise ValidationFailed(
            "请选择一个目标造型，或新建一个。", fields={"target_variant_id": "二选一"}
        )
    target: SkillAssetVariant | None = None
    if target_variant_id is not None:
        target = av.find_variant(skill, target_variant_id)
        if target is None:
            raise ValidationFailed("目标造型不存在。", fields={"target_variant_id": "不存在"})
        look = target
    else:
        assert new_variant is not None
        if av.is_character(skill) and len(skill.asset_variants) >= av.MAX_VARIANTS_PER_SKILL:
            raise ValidationFailed(
                f"每个角色最多 {av.MAX_VARIANTS_PER_SKILL} 个造型。",
                fields={"new_variant.name": "数量已达上限"},
            )
        if new_variant.scene_id is not None and not character:
            raise ValidationFailed(
                "只有角色造型可以关联场景。", fields={"new_variant.scene_id": "不支持"}
            )
        look = _draft_variant(skill, new_variant)
    if output == "identity_portrait" and not (target is not None and target.is_default):
        raise ValidationFailed(
            "定妆照只属于默认造型，请把目标设为默认造型。", fields={"output": "需要默认造型"}
        )
    if output == "in_scene" and look.scene_skill_id is None:
        raise ValidationFailed(
            "目标造型还没有关联场景，先在属性里选择场景。", fields={"output": "未关联场景"}
        )

    params: dict[str, Any] = {
        **_base(kind, skill, name),
        "source_entry_id": source.id,
        "prompt": _sentence(
            name,
            description,
            None if look.is_default else look.description,
            prompt_extra,
        )[:4096],
    }
    if target is not None:
        params["target_variant_id"] = target.id
    if output == "identity_portrait":
        params["character_portrait"] = True
        entry_type = AssetEntryType.IDENTITY_PORTRAIT.value
    elif output == "expression_sheet":
        params["character_expressions"] = list(
            dict.fromkeys(expressions or DEFAULT_FILL_EXPRESSIONS)
        )[:MAX_CHARACTER_EXPRESSIONS]
        entry_type = AssetEntryType.EXPRESSION_SHEET.value
    elif output == "in_scene":
        params["asset_output_mode"] = "in_scene"
        params["asset_output_entry_type"] = AssetEntryType.POSE.value
        entry_type = "in_scene"
    elif output == "shot":
        params["asset_output_entry_type"] = AssetEntryType.SHOT.value
        entry_type = AssetEntryType.SHOT.value
    else:
        entry_type = output
    if kind == "scene":
        # A scene image is drawn to its variant's presets (`scene_*`).
        for axis in ("lighting", "weather", "state", "period"):
            value = (look.presets_json or {}).get(axis)
            if value:
                params[f"scene_{axis}"] = value
    elif kind == "prop" and (look.presets_json or {}).get("prop_state"):
        params["prop_state"] = look.presets_json["prop_state"]
    params["aspect_ratio"] = aspect_ratio or DEFAULT_ASPECT.get(entry_type, "16:9")
    relations = (
        [] if look is source.variant else graph_service.relations_between(source.variant, look)
    )
    return Plan(
        skill=skill,
        source=source,
        params=params,
        relations=relations,
        target=target,
        new_variant=new_variant,
    )


# A composite or face-only image cannot be orbited as-is: a sheet would be
# re-drawn as a sheet from the side. A sheet source starts with a front
# single-figure pass the other poses then chain from (`camera_from_sheet`).
_ORBIT_SOURCE_TYPES: dict[str, frozenset[str]] = {
    "character": frozenset(
        {
            AssetEntryType.CHARACTER_SHEET,
            AssetEntryType.VIEW,
            AssetEntryType.POSE,
            AssetEntryType.OTHER,
        }
    ),
    "scene": frozenset({AssetEntryType.MASTER, AssetEntryType.SHOT, AssetEntryType.OTHER}),
    "prop": frozenset(
        {AssetEntryType.MASTER, AssetEntryType.VIEW, AssetEntryType.SHOT, AssetEntryType.OTHER}
    ),
}
FRONT_POSE = camera_vocab.CameraPose(0)


def orbit_poses(
    source: SkillAssetEntry, poses: list[camera_vocab.CameraPose]
) -> tuple[list[dict[str, Any]], bool]:
    """`(camera_poses params, camera_from_sheet)` for orbiting `source`:
    snapped, de-duplicated, and — for a character sheet — led by the front
    single figure the other poses are drawn from."""
    snapped: list[camera_vocab.CameraPose] = []
    for pose in poses:
        clean = camera_vocab.snap(pose)
        if clean.bucket() not in {p.bucket() for p in snapped}:
            snapped.append(clean)
    from_sheet = source.entry_type == AssetEntryType.CHARACTER_SHEET
    if from_sheet:
        snapped = [FRONT_POSE] + [p for p in snapped if p.bucket() != FRONT_POSE.bucket()]
    return [p.as_dict() for p in snapped], from_sheet


def plan_orbit(
    session: Session,
    *,
    user_id: str,
    kind: str,
    card_id: str,
    entry_id: str,
    poses: list[camera_vocab.CameraPose],
    aspect_ratio: str | None = None,
) -> Plan:
    """多机位: one image per pose of the source's subject, filed into the
    source's own look / variant (each pose is its own slot). Already-filled
    poses are not filtered here — a new one becomes a candidate."""
    skill, name, description = _card(session, user_id=user_id, kind=kind, card_id=card_id)
    source = _source(skill, entry_id)
    if source.entry_type not in _ORBIT_SOURCE_TYPES.get(kind, frozenset()):
        raise ValidationFailed(
            "这张图不能用来生成多机位：请选设定图、单人视图或场景图。",
            fields={"entry_id": "类型不支持"},
        )
    if not poses:
        raise ValidationFailed("请至少选择一个机位。", fields={"poses": "不能为空"})
    camera_poses, from_sheet = orbit_poses(source, poses)
    if len(camera_poses) > camera_vocab.MAX_CAMERA_POSES:
        raise ValidationFailed(
            f"一次最多生成 {camera_vocab.MAX_CAMERA_POSES} 个机位"
            + ("（从设定图生成时含正面全身）" if from_sheet else "")
            + "。",
            fields={"poses": "数量过多"},
        )
    params: dict[str, Any] = {
        **_base(kind, skill, name),
        "source_entry_id": source.id,
        "target_variant_id": source.variant_id,
        "camera_poses": camera_poses,
        "camera_from_sheet": from_sheet,
        "prompt": _sentence(name, description)[:4096],
        "aspect_ratio": aspect_ratio or {"character": "3:4", "prop": "1:1"}.get(kind, "16:9"),
    }
    return Plan(skill=skill, source=source, params=params, relations=[])
