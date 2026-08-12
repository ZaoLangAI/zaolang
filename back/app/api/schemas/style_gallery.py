"""Curated system style catalogue payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel


class StyleGalleryEntryResponse(ApiModel):
    id: str
    slug: str
    label_zh: str
    label_en: str
    label_ja: str
    description: str | None = None
    cover_asset_id: str | None = None
    cover_url: str | None = None
    params: dict[str, Any]
    sort_order: int
    is_active: bool
    apply_count: int
    created_at: dt.datetime


class StyleGalleryEntryCreateRequest(ApiModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    label_zh: str = Field(min_length=1, max_length=64)
    label_en: str = Field(min_length=1, max_length=64)
    label_ja: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=300)
    cover_asset_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class StyleGalleryEntryUpdateRequest(ApiModel):
    label_zh: str = Field(min_length=1, max_length=64)
    label_en: str = Field(min_length=1, max_length=64)
    label_ja: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=300)
    cover_asset_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    is_active: bool = True
