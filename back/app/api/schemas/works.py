"""Work, lineage, draft and community payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.models.enums import LicenseType, LifecycleStatus, MediaType, Visibility


class AuthorSummary(ApiModel):
    user_id: str
    display_name: str
    handle: str
    avatar_url: str | None = None


class WorkStats(ApiModel):
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    remix_count: int = 0


class WorkVersionSummary(ApiModel):
    id: str
    version_number: int
    title: str
    description: str | None = None
    cover_url: str | None = None
    media_url: str | None = None
    media_type: MediaType | None = None
    ai_generated: bool = True
    created_at: dt.datetime


class WorkSummary(ApiModel):
    """Card-sized projection used by discover, profile and collection lists."""

    id: str
    title: str
    visibility: Visibility
    lifecycle_status: LifecycleStatus
    cover_url: str | None = None
    media_type: MediaType | None = None
    author: AuthorSummary
    stats: WorkStats
    tags: list[str] = Field(default_factory=list)
    remixable: bool = False
    published_at: dt.datetime | None = None


class ReusableParams(ApiModel):
    """What a remixer can carry over.

    Only fields the author actually made reusable appear here; a licence that
    forbids derivatives yields an empty payload.
    """

    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    style_tags: list[str] = Field(default_factory=list)
    workflow_version_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LicenseInfo(ApiModel):
    license_type: LicenseType
    attribution_text: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    captured_at: dt.datetime | None = None


class LineageAncestor(ApiModel):
    work_version_id: str
    work_id: str
    title: str
    author: AuthorSummary | None = None
    depth: int
    is_tombstone: bool = False
    cover_url: str | None = None


class WorkDetail(WorkSummary):
    description: str | None = None
    current_version: WorkVersionSummary | None = None
    reusable_params: ReusableParams | None = None
    license: LicenseInfo | None = None
    ancestors: list[LineageAncestor] = Field(default_factory=list)
    descendant_count: int = 0
    viewer_liked: bool = False
    viewer_bookmarked: bool = False
    can_remix: bool = False
    remix_block_reason: str | None = None


class LineageNodeResponse(ApiModel):
    work_version_id: str
    work_id: str
    title: str
    author: dict[str, Any] = Field(default_factory=dict)
    depth: int
    is_tombstone: bool
    cover_url: str | None = None
    children: list[LineageNodeResponse] = Field(default_factory=list)


class LineageResponse(ApiModel):
    """Both directions in one payload so the graph renders in a single fetch."""

    root: LineageNodeResponse
    ancestors: list[LineageAncestor] = Field(default_factory=list)
    total_descendants: int = 0
    truncated: bool = False


class VersionDiffEntry(ApiModel):
    field: str
    parent_value: Any = None
    child_value: Any = None
    changed: bool = False


class VersionDiffResponse(ApiModel):
    parent_work_version_id: str
    child_work_version_id: str
    entries: list[VersionDiffEntry]


class DraftCreateRequest(ApiModel):
    source_work_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)


class DraftResponse(ApiModel):
    id: str
    source_work_version_id: str | None = None
    title: str | None = None
    description: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    license: LicenseInfo | None = None
    latest_job_id: str | None = None
    output_asset_id: str | None = None
    output_url: str | None = None
    published_work_id: str | None = None
    created_at: dt.datetime


class PublishRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Visibility = Visibility.PUBLIC_VIEW_ONLY
    tags: list[str] = Field(default_factory=list, max_length=10)
    cover_asset_id: str | None = None
    # Publishing requires an explicit statement that added material is cleared.
    rights_confirmed: bool = False
    ai_disclosure_confirmed: bool = False


class PublishResponse(ApiModel):
    work_id: str
    work_version_id: str
    visibility: Visibility
    lineage_edge_id: str | None = None
    royalties_paid: list[dict[str, Any]] = Field(default_factory=list)


class VisibilityUpdateRequest(ApiModel):
    visibility: Visibility


class CollectionCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_public: bool = True


class CollectionResponse(ApiModel):
    id: str
    name: str
    description: str | None = None
    is_public: bool
    item_count: int = 0
    cover_urls: list[str] = Field(default_factory=list)


class TagResponse(ApiModel):
    """A tag with all three labels.

    The client picks the label for its own locale rather than the server
    guessing from a header, so one cached response serves every language.
    """

    slug: str
    label_zh: str
    label_en: str
    label_ja: str
    usage_count: int = 0


class StylePresetCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    params: dict[str, Any]
    derived_from_work_version_id: str | None = None
    is_public: bool = False


class StylePresetResponse(ApiModel):
    id: str
    name: str
    description: str | None = None
    params: dict[str, Any]
    is_public: bool
    apply_count: int
    owner: AuthorSummary | None = None
