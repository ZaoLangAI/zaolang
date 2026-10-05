"""Owner-only view of a card's management graph (`asset_graph.service.graph`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.asset_graph import (
    AssetEdgeView,
    AssetGraphCaps,
    AssetGraphPendingJob,
    AssetGraphResponse,
)
from app.domain.asset_graph import service as graph_service
from app.domain.asset_graph.service import CardGraph
from app.domain.asset_variants import service as av
from app.domain.characters import voices as voices_service
from app.models import SkillAssetEdge
from app.models.enums import AssetEdgeOrigin, AssetGraphLevel, AssetRelation
from app.presenters import asset_variants as variant_presenter
from app.presenters import character_voices as voice_presenter


def edge_view(edge: SkillAssetEdge) -> AssetEdgeView:
    source, target = graph_service.endpoints(edge)
    return AssetEdgeView(
        id=edge.id,
        level=AssetGraphLevel(edge.level),
        source_id=source,
        target_id=target,
        relations=[AssetRelation(r) for r in edge.relations_json or []],
        label=edge.label,
        origin=AssetEdgeOrigin(edge.origin),
        source_job_id=edge.source_job_id,
        created_at=edge.created_at,
    )


def graph_response(
    session: Session, graph: CardGraph, *, description: str | None
) -> AssetGraphResponse:
    """`description` is the card view's full text (`CreationSkill.description`
    is a 300-char preview)."""
    skill = graph.skill
    character = av.is_character(skill)
    return AssetGraphResponse(
        card_id=skill.id,
        card_kind="character" if character else "scene",
        name=skill.title,
        description=description,
        anchor_entry_id=variant_presenter.anchor_entry_id(skill),
        variants=[variant_presenter.variant_view(session, v) for v in graph.variants],
        edges=[edge_view(edge) for edge in graph.edges],
        pending=[AssetGraphPendingJob(**row) for row in graph.pending],
        voices=[voice_presenter.voice_view(session, skill, voice) for voice in graph.voices],
        caps=AssetGraphCaps(
            max_variants=av.MAX_VARIANTS_PER_SKILL if character else None,
            max_entries_per_variant=av.MAX_ENTRIES_PER_VARIANT,
            max_entries=av.MAX_ENTRIES_PER_SKILL if character else None,
            max_edges=graph_service.MAX_EDGES_PER_SKILL,
            max_voices=voices_service.MAX_VOICES_PER_CHARACTER if character else None,
        ),
    )
