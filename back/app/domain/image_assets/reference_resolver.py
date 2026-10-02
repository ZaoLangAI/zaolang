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
   target's approved identity portrait, so every look is drawn from one face;
3. `params["reference_labels"]`: what each reference *is*
   (`角色「林夏」·婚礼·设定图`), for the prompt's 参考图说明 legend.

`shot_hint` / `emotion_hint` are accepted for the P2 ranking (close-up →
portrait + matching expression, wide → turnaround) and ignored for now.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters import service as characters_service
from app.domain.errors import NotFound
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill


def resolve(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    shot_hint: str | None = None,
    emotion_hint: str | None = None,
) -> None:
    # Server-written below; a client never sets it.
    params.pop("reference_labels", None)
    characters_service.apply_character_refs(session, user_id=user_id, params=params)
    _borrow_expression_reference(session, user_id=user_id, params=params)
    _borrow_identity_reference(session, user_id=user_id, params=params)
    scenes_service.apply_scene_refs(session, user_id=user_id, params=params)
    _label_references(session, user_id=user_id, params=params)


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


def _borrow_identity_reference(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """A character sheet or portrait job with no reference at all but a
    named target starts from that card's approved identity portrait (定妆照)
    — the face every look shares. A stale target is left to write-back's
    own fallback rather than failing the submit."""
    if params.get("asset_kind") != "character" or params.get("reference_asset_ids"):
        return
    if params.get("character_expressions"):
        return
    target_id = params.get("target_character_id")
    if not target_id:
        return
    try:
        character = characters_service.get_character(
            session, user_id=user_id, character_id=str(target_id)
        )
    except NotFound:
        return
    portrait = asset_variants_service.identity_portrait(character.skill)
    if portrait is not None:
        params["reference_asset_ids"] = [portrait.asset_id]


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


def _label_references(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """Writes `params["reference_labels"]` for every reference this job's
    picked/targeted cards can name; leaves it unset when there are none."""
    wanted = {str(asset_id) for asset_id in params.get("reference_asset_ids") or []}
    if not wanted:
        return
    labels: dict[str, str] = {}
    for card in _owned_cards(session, user_id=user_id, params=params):
        for entry in asset_variants_service.entries(card):
            if entry.asset_id in wanted and entry.asset_id not in labels:
                labels[entry.asset_id] = asset_variants_service.entry_label(card, entry)
    if labels:
        params["reference_labels"] = [
            {"asset_id": asset_id, "label": label} for asset_id, label in labels.items()
        ]
