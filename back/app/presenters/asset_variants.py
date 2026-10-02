"""Signed, read-only views of a card's looks / variants and their images.

Signs per request (`media_urls.asset_url`) — callers decide access first
(MA invariant 5): the owner's own card, or an unlocked marketplace card.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.asset_variants import AssetEntryView, AssetVariantView
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
        expressions=[str(item) for item in entry.expressions_json or []],
        label=entry.label,
        status=AssetEntryStatus(entry.status),
        is_anchor=entry.is_anchor,
        source_job_id=entry.source_job_id,
        created_at=entry.created_at,
    )


def variant_view(
    session: Session, variant: SkillAssetVariant, *, approved_only: bool = False
) -> AssetVariantView:
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
