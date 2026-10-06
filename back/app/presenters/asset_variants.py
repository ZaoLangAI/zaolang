"""Signed, read-only views of a card's looks / variants and their images.

Signs per request (`media_urls.asset_url`) — callers decide access first
(MA invariant 5): the owner's own card, or an unlocked marketplace card.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.asset_variants import (
    AssetEntryView,
    AssetVariantView,
    CameraPose,
    SceneLinkView,
    VariantAttributes,
)
from app.domain.asset_variants import service as asset_variants_service
from app.models import CreationSkill, SkillAssetEntry, SkillAssetVariant
from app.models.enums import AssetEntryStatus, AssetEntryType
from app.presenters import media_urls


def entry_view(session: Session, entry: SkillAssetEntry) -> AssetEntryView:
    return AssetEntryView(
        id=entry.id,
        asset_id=entry.asset_id,
        url=media_urls.asset_url(session, entry.asset_id),
        entry_type=AssetEntryType(entry.entry_type),
        view=entry.view,
        camera=CameraPose.model_validate(entry.camera_json) if entry.camera_json else None,
        expressions=[str(item) for item in entry.expressions_json or []],
        label=entry.label,
        status=AssetEntryStatus(entry.status),
        is_anchor=entry.is_anchor,
        source_job_id=entry.source_job_id,
        created_at=entry.created_at,
    )


def scene_link_view(session: Session, variant: SkillAssetVariant) -> SceneLinkView | None:
    if variant.scene_skill_id is None:
        return None
    scene = session.get(CreationSkill, variant.scene_skill_id)
    if scene is None:
        return None
    scene_variant = (
        asset_variants_service.find_variant(scene, variant.scene_variant_id)
        if variant.scene_variant_id
        else None
    )
    thumb = asset_variants_service.master_or_anchor(scene, scene_variant)
    return SceneLinkView(
        scene_id=scene.id,
        scene_name=scene.title,
        variant_id=scene_variant.id if scene_variant else None,
        variant_name=scene_variant.name if scene_variant else None,
        thumb_url=media_urls.asset_url(session, thumb.asset_id) if thumb else None,
    )


def variant_view(
    session: Session, variant: SkillAssetVariant, *, approved_only: bool = False
) -> AssetVariantView:
    """`approved_only` is the public (unlocked) view: no candidates, no
    scene link. `voice_id` stays — voices unlock with the card."""
    shown = [
        entry
        for entry in variant.entries
        if not approved_only or asset_variants_service.is_approved(entry)
    ]
    return AssetVariantView(
        id=variant.id,
        name=variant.name,
        description=variant.description,
        presets=dict(variant.presets_json or {}),
        attributes=VariantAttributes.model_validate(variant.attributes_json or {}),
        scene_link=None if approved_only else scene_link_view(session, variant),
        voice_id=variant.voice_id,
        is_default=variant.is_default,
        sort_order=variant.sort_order,
        entries=[entry_view(session, entry) for entry in shown],
    )


def variant_views(
    session: Session, skill: CreationSkill, *, approved_only: bool = False
) -> list[AssetVariantView]:
    """Every look with its images. `approved_only` drops candidates — for
    anyone but the owner's own editor (an unlocked marketplace card)."""
    return [
        variant_view(session, v, approved_only=approved_only)
        for v in asset_variants_service.variants(skill)
    ]


def anchor_entry_id(skill: CreationSkill) -> str | None:
    anchor = asset_variants_service.anchor(skill)
    return anchor.id if anchor else None
