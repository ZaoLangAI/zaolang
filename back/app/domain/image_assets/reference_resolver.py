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
   the prompt builder;
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
from app.domain.errors import NotFound
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill
from app.models.enums import AssetEntryType


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
    hints = asset_variants_service.ReferenceHints(
        shot=shot_hint or params.get("reference_shot_size") or _prompt_shot_size(params),
        emotion=emotion_hint or params.get("reference_emotion"),
    )
    characters_service.apply_character_refs(session, user_id=user_id, params=params, hints=hints)
    _borrow_expression_reference(session, user_id=user_id, params=params)
    roles = _borrow_identity_reference(session, user_id=user_id, params=params)
    scenes_service.apply_scene_refs(session, user_id=user_id, params=params, hints=hints)
    _label_references(session, user_id=user_id, params=params, roles=roles)


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
MAX_BORROWED_REFERENCES = 3


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
    age_stage = (look.presets_json or {}).get("age_stage") if look is not None else None
    if look is not None and (not look.is_default or look.description or age_stage):
        params["target_look"] = {
            "name": None if look.is_default else look.name,
            "description": look.description,
            "age_stage": age_stage,
        }
    if params.get("reference_asset_ids") or params.get("character_expressions"):
        return {}

    outfit_change = (look is not None and not look.is_default) or bool(
        params.get("character_outfit_label")
    )
    roles: dict[str, str] = {}
    picked: list[str] = []
    portrait = asset_variants_service.identity_portrait(skill)
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


_CAMERA_LINE = re.compile(r"镜头[：:]\s*([^\n]+)")


def _prompt_shot_size(params: dict[str, Any]) -> str | None:
    """The shot size named in the prompt's 「镜头：」 line, if any. Only that
    line — 「特写」 elsewhere in a description says nothing about framing."""
    match = _CAMERA_LINE.search(str(params.get("prompt") or ""))
    return camera_language.parse_camera_text(match.group(1)).size if match else None


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
) -> None:
    """Writes `params["reference_labels"]` for every reference this job's
    picked/targeted cards can name; leaves it unset when there are none.
    `roles` appends what to take from a borrowed image (面部 / 服装)."""
    wanted = {str(asset_id) for asset_id in params.get("reference_asset_ids") or []}
    if not wanted:
        return
    labels: dict[str, str] = {}
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
