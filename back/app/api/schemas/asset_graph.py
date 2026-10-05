"""A card's management graph (P4): its looks / variants with their images,
the typed edges between them, and jobs still filling it — one read for the
`/create/{characters|scenes}/[id]` page."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.api.schemas.asset_variants import AssetVariantView
from app.api.schemas.common import ApiModel
from app.domain.asset_graph.service import MAX_EDGE_LABEL_LEN, MAX_RELATIONS_PER_EDGE
from app.models.enums import AssetEdgeOrigin, AssetGraphLevel, AssetRelation


class AssetEdgeView(ApiModel):
    id: str
    level: AssetGraphLevel
    source_id: str
    target_id: str
    relations: list[AssetRelation]
    label: str | None = None
    origin: AssetEdgeOrigin
    source_job_id: str | None = None
    created_at: dt.datetime | None = None


class AssetGraphCaps(ApiModel):
    """`None` = uncapped (a scene card's variants and total images)."""

    max_variants: int | None = None
    max_entries_per_variant: int
    max_entries: int | None = None
    max_edges: int


class AssetGraphPendingJob(ApiModel):
    """A generation job still filling this card (P6 fills it in)."""

    job_id: str
    status: str
    mode: str | None = None
    target_variant_id: str | None = None
    source_entry_id: str | None = None


class AssetGraphResponse(ApiModel):
    card_id: str
    card_kind: Literal["character", "scene"]
    name: str
    description: str | None = None
    anchor_entry_id: str | None = None
    variants: list[AssetVariantView] = Field(default_factory=list)
    edges: list[AssetEdgeView] = Field(default_factory=list)
    pending: list[AssetGraphPendingJob] = Field(default_factory=list)
    caps: AssetGraphCaps


class AssetEdgeCreateRequest(ApiModel):
    level: Literal["variant", "entry"]
    source_id: str = Field(max_length=40)
    target_id: str = Field(max_length=40)
    relations: list[AssetRelation] = Field(min_length=1, max_length=MAX_RELATIONS_PER_EDGE)
    label: str | None = Field(default=None, max_length=MAX_EDGE_LABEL_LEN)


class AssetEdgeUpdateRequest(ApiModel):
    """`label: null` leaves it; send `clear_label` to unset it."""

    relations: list[AssetRelation] | None = Field(
        default=None, min_length=1, max_length=MAX_RELATIONS_PER_EDGE
    )
    label: str | None = Field(default=None, max_length=MAX_EDGE_LABEL_LEN)
    clear_label: bool = False
