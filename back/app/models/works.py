"""Works, versions, lineage, licensing and community interactions."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import (
    DistributionChannel,
    LicenseType,
    LifecycleStatus,
    PublicationStatus,
    Visibility,
)


class Work(Base, TimestampMixin):
    __tablename__ = "works"

    id: Mapped[str] = id_column("wrk")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    current_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Set at publish time from the draft's params. Episode-number uniqueness
    # within a series is enforced in the service layer, not a DB constraint,
    # to sidestep the SQLite/Postgres partial-index syntax split.
    series_id: Mapped[str | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True
    )
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(24), default=Visibility.PUBLIC_VIEW_ONLY, nullable=False
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(24), default=LifecycleStatus.ACTIVE, nullable=False
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstoned_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tombstone_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    view_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    remix_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    versions: Mapped[list[WorkVersion]] = relationship(
        back_populates="work", foreign_keys="WorkVersion.work_id"
    )

    __table_args__ = (
        Index("ix_works_owner_user_id", "owner_user_id"),
        Index("ix_works_visibility_lifecycle_status", "visibility", "lifecycle_status"),
        Index("ix_works_published_at", "published_at"),
        Index("ix_works_series_id_episode_number", "series_id", "episode_number"),
    )

    @property
    def is_publicly_visible(self) -> bool:
        return (
            self.lifecycle_status == LifecycleStatus.ACTIVE
            and Visibility(self.visibility).is_publicly_listed
        )


class WorkVersion(Base):
    """Immutable published snapshot. Lineage points at versions, not works, so
    later edits to a parent cannot rewrite a child's provenance."""

    __tablename__ = "work_versions"

    id: Mapped[str] = id_column("wv")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    primary_output_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    workflow_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True
    )
    generation_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    license_snapshot_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Reusable prompt / parameter payload shown on the work detail page.
    reusable_params_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    immutable_created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    work: Mapped[Work] = relationship(back_populates="versions", foreign_keys=[work_id])

    __table_args__ = (
        UniqueConstraint("work_id", "version_number", name="uq_work_versions_work_version"),
        Index("ix_work_versions_work_id", "work_id"),
    )


class LicenseSnapshot(Base):
    """Frozen copy of the licence terms at the moment a remix was authorised.

    Later licence changes by the original author never rewrite this record.
    """

    __tablename__ = "license_snapshots"

    id: Mapped[str] = id_column("lic")
    license_type: Mapped[str] = mapped_column(
        String(32), default=LicenseType.CC_BY_4_0, nullable=False
    )
    permissions_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    attribution_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_work_version_id: Mapped[str] = mapped_column(
        ForeignKey("work_versions.id", ondelete="RESTRICT"), nullable=False
    )
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_license_snapshots_source", "source_work_version_id"),)


class LineageEdge(Base):
    """The unbreakable link between a parent and child version.

    Exactly one edge exists per published remix version, enforced by the unique
    constraint on `child_work_version_id`. `ondelete=RESTRICT` on the parent is
    what stops anyone deleting a source record that descendants still cite.
    """

    __tablename__ = "lineage_edges"

    id: Mapped[str] = id_column("lin")
    parent_work_version_id: Mapped[str] = mapped_column(
        ForeignKey("work_versions.id", ondelete="RESTRICT"), nullable=False
    )
    child_work_version_id: Mapped[str] = mapped_column(
        ForeignKey("work_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    parent_author_snapshot_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    license_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("license_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True
    )
    reused_asset_ids_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_lineage_edges_parent", "parent_work_version_id"),
        Index("ix_lineage_edges_created_by", "created_by_user_id"),
    )


class Draft(Base, TimestampMixin):
    """Work in progress between "start a remix" and "publish".

    Carries the licence snapshot captured at creation time so that publishing
    validates against the terms the remixer actually accepted.
    """

    __tablename__ = "drafts"

    id: Mapped[str] = id_column("drf")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_work_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_versions.id", ondelete="RESTRICT"), nullable=True
    )
    license_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("license_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    latest_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    output_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    published_work_id: Mapped[str | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_drafts_user_id", "user_id"),)


class PublicationIntent(Base, TimestampMixin):
    """One attempt to take a published work off-platform.

    Recorded even when the user only downloads the file, so the export history
    of a work is answerable without depending on a distribution channel that
    does not exist yet. `external_post_id` and `submitted_at` stay null until a
    real direct-publish integration fills them in.
    """

    __tablename__ = "publication_intents"

    id: Mapped[str] = id_column("pub")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), default=DistributionChannel.MANUAL_DOWNLOAD, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default=PublicationStatus.DRAFT, nullable=False)
    # Caption, hashtags, cover and schedule as submitted by the creator.
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    external_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_publication_intents_work_id", "work_id"),
        Index("ix_publication_intents_user_id_channel", "user_id", "channel"),
    )


class Like(Base, TimestampMixin):
    __tablename__ = "likes"

    id: Mapped[str] = id_column("lke")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "work_id", name="uq_likes_user_work"),)


class Bookmark(Base, TimestampMixin):
    __tablename__ = "bookmarks"

    id: Mapped[str] = id_column("bkm")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "work_id", name="uq_bookmarks_user_work"),)


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

    id: Mapped[str] = id_column("col")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CollectionItem(Base, TimestampMixin):
    __tablename__ = "collection_items"

    id: Mapped[str] = id_column("cli")
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("collection_id", "work_id", name="uq_collection_items_pair"),
    )


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[str] = id_column("tag")
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label_zh: Mapped[str] = mapped_column(String(64), nullable=False)
    label_en: Mapped[str] = mapped_column(String(64), nullable=False)
    label_ja: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WorkTag(Base, TimestampMixin):
    __tablename__ = "work_tags"

    id: Mapped[str] = id_column("wtg")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (UniqueConstraint("work_id", "tag_id", name="uq_work_tags_pair"),)


class StylePreset(Base, TimestampMixin):
    """Saved, shareable generation parameters distilled from a work."""

    __tablename__ = "style_presets"

    id: Mapped[str] = id_column("stp")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    derived_from_work_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_versions.id", ondelete="SET NULL"), nullable=True
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    apply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (Index("ix_style_presets_owner", "owner_user_id"),)
