"""One place that turns a job's characters/scenes into reference images.

`resolve` runs at submit (`jobs.service.submit`), before quoting:

1. the picked characters' and scenes' images — each card contributes its
   `*_ref_selection` (a look/variant, exact images, or both) or its default
   subset (`asset_variants.service.default_subset`) — merged after the
   caller's explicit uploads into the shared 9-slot `reference_asset_ids`,
   plus the characters' voice hints (`characters.service.apply_character_refs`
   / `scenes.service.apply_scene_refs`);
2. a composite expression image with no reference at all borrows its target
   character's sheet (from `target_variant_id`'s look when given); any other
   character image (sheet, identity portrait) with no reference borrows the
   target's approved identity portrait, so every look is drawn from one face.
   A 换装 job (a non-default target look, or a `character_outfit_label`) also
   borrows that look's own sheet and its `outfit_detail` uploads; with no
   portrait it falls back to the default look's sheet for the face, and the
   legend says which image is for the face and which for the clothes (P2-3);
   `params["target_look"]` carries the look's name and outfit description to
   the prompt builder; a scene image with no reference but a target scene
   (a matrix cell, P2-5) borrows that card's anchor master plate, or the
   target variant's own images;
3. `params["reference_labels"]`: what each reference *is*
   (`角色「林夏」·婚礼·设定图`), for the prompt's 参考图说明 legend.

Default references are ranked for the shot (P2-7,
`asset_variants.service.ReferenceHints`): `shot_hint` / `emotion_hint`, else
`reference_shot_size` / `reference_emotion`, else the shot size in the
prompt's 「镜头：」 line — what a script segment's camera block becomes
(`front/src/features/script/script-prompts.ts`), read with the blockout's
own camera grammar (`blocking.camera_language.parse_camera_text`).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.domain.asset_variants import service as asset_variants_service
from app.domain.blocking import camera_language
from app.domain.characters import service as characters_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill, SkillAssetVariant
from app.models.enums import AssetEntryType, CharacterViewAngle


def resolve(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    shot_hint: str | None = None,
    emotion_hint: str | None = None,
) -> None:
    # Server-written below; a client never sets either.
    params.pop("reference_labels", None)
    params.pop("target_look", None)
    # The per-pass camera pose is written into `extra` by the workflow
    # (`nodes.execute_asset_planning`) from `camera_poses`; a client-sent
    # one would steer the camera-control route on any image job.
    extra = params.get("extra")
    if isinstance(extra, dict) and "camera_pose" in extra:
        params["extra"] = {k: v for k, v in extra.items() if k != "camera_pose"}
    cue = _prompt_camera_cue(params)
    hints = asset_variants_service.ReferenceHints(
        shot=shot_hint or params.get("reference_shot_size") or (cue.size if cue else None),
        emotion=emotion_hint or params.get("reference_emotion"),
        side=params.get("reference_camera_side") or (cue.side if cue else None),
        height=params.get("reference_camera_height") or (cue.height if cue else None),
    )
    source_roles, foreign_labels = _source_entry_reference(session, user_id=user_id, params=params)
    characters_service.apply_character_refs(session, user_id=user_id, params=params, hints=hints)
    _borrow_expression_reference(session, user_id=user_id, params=params)
    roles = {**source_roles, **_borrow_identity_reference(session, user_id=user_id, params=params)}
    scenes_service.apply_scene_refs(session, user_id=user_id, params=params, hints=hints)
    _borrow_scene_reference(session, user_id=user_id, params=params)
    _label_references(session, user_id=user_id, params=params, roles=roles, foreign=foreign_labels)


def _borrow_expression_reference(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """A composite expression image is drawn *from* the character's sheet:
    with no reference at all but a named target, borrow the target's
    default subset (of `target_variant_id`'s look when given)."""
    if not params.get("character_expressions") or params.get("reference_asset_ids"):
        return
    target_id = params.get("target_character_id")
    if not target_id:
        return
    character = characters_service.get_character(
        session, user_id=user_id, character_id=str(target_id)
    )
    params["reference_asset_ids"] = characters_service.default_reference_asset_ids(
        character, variant_id=params.get("target_variant_id")
    )


# How the legend tells the model what to take from a borrowed image (P2-3).
FACE_ONLY_ROLE = "（只取面部与体型，忽略服装）"
OUTFIT_ONLY_ROLE = "（只取服装）"
# P6: the image a derive / adjust starts from, and the scene an `in_scene`
# character is placed into.
SOURCE_ROLE = "（以此图为基础）"
SCENE_ONLY_ROLE = "（只取场景环境与光线，忽略其中的人物）"
MAX_BORROWED_REFERENCES = 3
MAX_REFERENCES = 9


def _source_entry_reference(
    session: Session, *, user_id: str, params: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """`source_entry_id` (P6): an image of the job's own target card, put
    first in `reference_asset_ids`. An `in_scene` job also borrows the
    target look's linked scene still (`master_or_anchor`). Another card's
    image, or an `in_scene` look with no scene, is a 422. Returns the legend
    roles and the labels of images from cards the job does not name (the
    linked scene's still)."""
    entry_id = params.get("source_entry_id")
    if not entry_id:
        return {}, {}
    character = params.get("asset_kind") == "character"
    card_id = params.get("target_character_id" if character else "target_scene_id")
    if not card_id:
        raise ValidationFailed(
            "基于参考图生成需要指定目标卡片。", fields={"source_entry_id": "缺少卡片"}
        )
    skill = (
        characters_service.get_character(session, user_id=user_id, character_id=str(card_id))
        if character
        else scenes_service.get_scene(session, user_id=user_id, scene_id=str(card_id))
    ).skill
    entry = asset_variants_service.find_entry(skill, str(entry_id))
    if entry is None:
        raise ValidationFailed("参考图不在这张卡片上。", fields={"source_entry_id": "图片不存在"})
    refs = [entry.asset_id] + [
        str(r) for r in params.get("reference_asset_ids") or [] if str(r) != entry.asset_id
    ]
    roles = {entry.asset_id: SOURCE_ROLE}
    foreign: dict[str, str] = {}
    if character and params.get("camera_poses"):
        # 多机位 (AC-2): a camera route reads reference 1 only; a
        # prompt-only fallback also gets the card's face to hold on to.
        portrait = asset_variants_service.identity_portrait(skill)
        if portrait is not None and portrait.asset_id != entry.asset_id:
            refs = [refs[0], portrait.asset_id] + [r for r in refs[1:] if r != portrait.asset_id]
            roles[portrait.asset_id] = FACE_ONLY_ROLE
    if params.get("asset_output_mode") == "in_scene":
        look_id = params.get("target_variant_id")
        look = asset_variants_service.find_variant(skill, str(look_id)) if look_id else None
        scene = (
            session.get(CreationSkill, look.scene_skill_id)
            if look and look.scene_skill_id
            else None
        )
        if look is None or scene is None:
            raise ValidationFailed(
                "这个造型还没有关联场景，先在造型属性里选择场景。",
                fields={"target_variant_id": "未关联场景"},
            )
        scene_variant = (
            asset_variants_service.find_variant(scene, look.scene_variant_id)
            if look.scene_variant_id
            else None
        )
        still = asset_variants_service.master_or_anchor(scene, scene_variant)
        if still is None:
            raise ValidationFailed(
                "关联的场景还没有图片，先为场景生成一张主图。",
                fields={"target_variant_id": "场景没有图片"},
            )
        refs = [r for r in refs if r != still.asset_id] + [still.asset_id]
        roles[still.asset_id] = SCENE_ONLY_ROLE
        foreign[still.asset_id] = asset_variants_service.entry_label(scene, still)
    params["reference_asset_ids"] = refs[:MAX_REFERENCES]
    return roles, foreign


def _target_look(look: SkillAssetVariant) -> dict[str, Any]:
    """`params["target_look"]` (`TargetLook`): what the prompt needs to know
    about the look a job files into — name (non-default only), outfit text,
    age stage, period and the free-text attributes (P3)."""
    presets = look.presets_json or {}
    attributes = look.attributes_json or {}
    return {
        "name": None if look.is_default else look.name,
        "description": look.description,
        "age_stage": presets.get("age_stage"),
        "period": presets.get("period"),
        "outfit": attributes.get("outfit"),
        "state": attributes.get("state"),
        "scene_note": attributes.get("scene_note"),
        "custom": [dict(item) for item in attributes.get("custom") or []],
    }


def _borrow_identity_reference(
    session: Session, *, user_id: str, params: dict[str, Any]
) -> dict[str, str]:
    """A character sheet or portrait job with no reference at all but a
    named target starts from that card's approved identity portrait (定妆照)
    — the face every look shares. A 换装 job also takes the target look's
    own approved sheet and its `outfit_detail` uploads, and with no portrait
    the default look's sheet stands in for the face. Writes
    `params["target_look"]` for a picked look. Returns the legend roles of
    borrowed images (`asset_id → suffix`). A stale target is left to
    write-back's own fallback rather than failing the submit."""
    if params.get("asset_kind") != "character":
        return {}
    target_id = params.get("target_character_id")
    if not target_id:
        return {}
    try:
        character = characters_service.get_character(
            session, user_id=user_id, character_id=str(target_id)
        )
    except NotFound:
        return {}
    skill = character.skill
    variant_id = params.get("target_variant_id")
    look = asset_variants_service.find_variant(skill, str(variant_id)) if variant_id else None
    if look is not None:
        target_look = _target_look(look)
        if not look.is_default or any(target_look.values()):
            params["target_look"] = target_look
    if params.get("reference_asset_ids") or params.get("character_expressions"):
        return {}

    portrait = asset_variants_service.identity_portrait(skill)
    views = params.get("character_views") or []
    if views and CharacterViewAngle.FRONT.value not in views:
        # Side/back only (补齐缺失 with the front sheet already there): the
        # completion prompt draws "from this image", so the look's approved
        # front sheet is reference 1; the portrait keeps the face.
        front = _approved_of(
            look or asset_variants_service.find_default(skill), AssetEntryType.CHARACTER_SHEET
        )
        completion = [e.asset_id for e in front[:1]] + ([portrait.asset_id] if portrait else [])
        if completion:
            params["reference_asset_ids"] = list(dict.fromkeys(completion))
        return {}

    outfit_change = (look is not None and not look.is_default) or bool(
        params.get("character_outfit_label")
    )
    roles: dict[str, str] = {}
    picked: list[str] = []
    if portrait is not None:
        picked.append(portrait.asset_id)
    own = _approved_of(look, AssetEntryType.CHARACTER_SHEET) if outfit_change else []
    picked.extend(e.asset_id for e in own)
    if outfit_change and portrait is None and not own:
        # No face to lock to but the default look's sheet — use it for the
        # face only, or the old outfit would leak into the new one.
        face = _approved_of(
            asset_variants_service.find_default(skill), AssetEntryType.CHARACTER_SHEET
        )
        for entry in face[:1]:
            picked.append(entry.asset_id)
            roles[entry.asset_id] = FACE_ONLY_ROLE
    if outfit_change:
        for entry in _approved_of(look, AssetEntryType.OUTFIT_DETAIL):
            picked.append(entry.asset_id)
            roles[entry.asset_id] = OUTFIT_ONLY_ROLE
    picked = list(dict.fromkeys(picked))[:MAX_BORROWED_REFERENCES]
    if picked:
        params["reference_asset_ids"] = picked
    return {asset_id: role for asset_id, role in roles.items() if asset_id in picked}


def _borrow_scene_reference(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """A scene image with no reference at all but a named target — a matrix
    cell (P2-5), whose new variant is still empty — starts from that card:
    `target_variant_id`'s own images when given, else the card's anchor, the
    master plate whose structure every variant keeps (`SCENE_VARIANT_PREFIX`
    locks reference 1). A stale target is left to write-back's fallback."""
    if params.get("asset_kind") != "scene" or params.get("reference_asset_ids"):
        return
    target_id = params.get("target_scene_id")
    if not target_id:
        return
    try:
        skill = scenes_service.get_scene(session, user_id=user_id, scene_id=str(target_id)).skill
    except NotFound:
        return
    variant_id = params.get("target_variant_id")
    variant = asset_variants_service.find_variant(skill, str(variant_id)) if variant_id else None
    anchor = asset_variants_service.anchor(skill)
    if variant is not None:
        picked = asset_variants_service.default_subset(skill, variant)
    elif anchor is not None and asset_variants_service.is_approved(anchor):
        picked = [anchor.asset_id]
    else:
        picked = asset_variants_service.default_subset(skill)
    if picked:
        params["reference_asset_ids"] = picked


_CAMERA_LINE = re.compile(r"镜头[：:]\s*([^\n]+)")


def _prompt_camera_cue(params: dict[str, Any]) -> camera_language.CameraCue | None:
    """The prompt's 「镜头：」 line read as camera language — shot size, and
    the side / height it sees the subject from (AC-3). Only that line —
    「特写」 or 「背影」 elsewhere in a description says nothing about the
    camera."""
    match = _CAMERA_LINE.search(str(params.get("prompt") or ""))
    return camera_language.parse_camera_text(match.group(1)) if match else None



def _approved_of(variant: Any, entry_type: AssetEntryType) -> list[Any]:
    if variant is None:
        return []
    return [
        e
        for e in variant.entries
        if asset_variants_service.is_approved(e) and e.entry_type == entry_type
    ]


def _card_ids(params: dict[str, Any], list_key: str, target_key: str) -> list[str]:
    raw = params.get(list_key)
    ids = [str(item) for item in raw] if isinstance(raw, list) else []
    target = params.get(target_key)
    if target and str(target) not in ids:
        ids.append(str(target))
    return ids


def _owned_cards(session: Session, *, user_id: str, params: dict[str, Any]) -> list[CreationSkill]:
    """The job's picked and targeted cards the caller owns (a stale id is
    skipped — the legend just names fewer images)."""
    cards: list[CreationSkill] = []
    for character_id in _card_ids(params, "character_ids", "target_character_id"):
        try:
            cards.append(
                characters_service.get_character(
                    session, user_id=user_id, character_id=character_id
                ).skill
            )
        except NotFound:
            continue
    for scene_id in _card_ids(params, "scene_ids", "target_scene_id"):
        try:
            cards.append(
                scenes_service.get_scene(session, user_id=user_id, scene_id=scene_id).skill
            )
        except NotFound:
            continue
    return cards


def _label_references(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    roles: dict[str, str] | None = None,
    foreign: dict[str, str] | None = None,
) -> None:
    """Writes `params["reference_labels"]` for every reference this job's
    picked/targeted cards can name; leaves it unset when there are none.
    `roles` appends what to take from a borrowed image (面部 / 服装);
    `foreign` names images from cards the job does not name."""
    wanted = {str(asset_id) for asset_id in params.get("reference_asset_ids") or []}
    if not wanted:
        return
    labels: dict[str, str] = {
        asset_id: label for asset_id, label in (foreign or {}).items() if asset_id in wanted
    }
    for card in _owned_cards(session, user_id=user_id, params=params):
        for entry in asset_variants_service.entries(card):
            if entry.asset_id in wanted and entry.asset_id not in labels:
                labels[entry.asset_id] = asset_variants_service.entry_label(card, entry)
    for asset_id, role in (roles or {}).items():
        if asset_id in labels:
            labels[asset_id] = labels[asset_id][: 60 - len(role)] + role
    if labels:
        params["reference_labels"] = [
            {"asset_id": asset_id, "label": label} for asset_id, label in labels.items()
        ]
