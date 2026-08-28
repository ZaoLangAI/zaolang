"""Short-drama editing aggregates: episodes, cuts, revisions, variants, exports."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import (
    DeliveryVariantStatus,
    DramaEpisodeStatus,
    EditorCommandEventStatus,
    EditorExportStatus,
    EditPlanStatus,
    EpisodeContentRole,
    EpisodeCutKind,
    EpisodeCutStatus,
    EpisodeKind,
    MediaAnalysisStatus,
)


class DramaEpisode(Base, TimestampMixin):
    """Production-time episode. Published `Work` remains the public projection."""

    __tablename__ = "drama_episodes"

    id: Mapped[str] = id_column("dep")
    series_id: Mapped[str] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False
    )
    # Uniqueness is scoped to `(series_id, season_number, episode_number)`,
    # not just `(series_id, episode_number)` — a trailer or a season 2
    # episode 1 must not collide with season 1 episode 1. Default 1 so every
    # pre-existing row (and every caller that doesn't think about seasons)
    # behaves exactly as before.
    season_number: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_kind: Mapped[str] = mapped_column(
        String(16), default=EpisodeKind.MAIN, server_default=EpisodeKind.MAIN.value, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=DramaEpisodeStatus.DRAFT, nullable=False
    )
    canonical_work_id: Mapped[str | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "season_number",
            "episode_number",
            name="uq_drama_episodes_series_season_number",
        ),
        Index("ix_drama_episodes_series_id", "series_id"),
    )


class EpisodeContentLink(Base, TimestampMixin):
    """Material associated with an episode without being its canonical
    output — a script draft still being iterated on, a batch of candidate
    image/video drafts, a finished `EditorExport` kept as a behind-the-scenes
    clip. `canonical_work_id` on `DramaEpisode` (not a `FINAL`-role row here)
    is what publishing and the public projection actually trust; a `FINAL`
    link is only a history breadcrumb of how that choice was made.

    `content_ref_id` is a bare id, not a foreign key — `content_type` names
    which table it belongs to (`draft` / `work` / `editor_export`), and a
    single polymorphic FK across three tables isn't expressible in SQL, so
    ownership is re-checked in the service layer on every read/write instead
    of being enforced by the database (same trade-off `AuditLog.target_id`
    makes — see `zaolang-data-model`).
    """

    __tablename__ = "episode_content_links"

    id: Mapped[str] = id_column("ecl")
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("drama_episodes.id", ondelete="CASCADE"), nullable=False
    )
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_ref_id: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str] = mapped_column(
        String(24), default=EpisodeContentRole.CANDIDATE, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "episode_id",
            "content_type",
            "content_ref_id",
            name="uq_episode_content_links_episode_content",
        ),
        Index("ix_episode_content_links_episode_id", "episode_id"),
    )


class EpisodeCut(Base, TimestampMixin):
    __tablename__ = "episode_cuts"

    id: Mapped[str] = id_column("cut")
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("drama_episodes.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), default=EpisodeCutKind.FULL, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=EpisodeCutStatus.DRAFT, nullable=False)
    # Same pattern as Work.current_version_id: no FK, avoids a cycle with revisions.
    head_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_cut_id: Mapped[str | None] = mapped_column(
        ForeignKey("episode_cuts.id", ondelete="SET NULL"), nullable=True
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    source_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("episode_id", "kind", "name", name="uq_episode_cuts_episode_kind_name"),
        Index("ix_episode_cuts_episode_id", "episode_id"),
    )


class EpisodeScriptTurn(Base, TimestampMixin):
    """One conversational turn of script writing. Immutable, append-only —
    each turn snapshots the *entire* script document as it stood after that
    turn, mirroring `CutRevision`'s revision chain but for
    `DramaEpisode.script_json` instead of a cut's timeline.

    `DramaEpisode.script_json` always holds the latest turn's
    `script_snapshot_json` (the "head"); this table exists purely so a user
    can click back into any earlier turn and see the exact script that turn
    produced.
    """

    __tablename__ = "episode_script_turns"

    id: Mapped[str] = id_column("est")
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("drama_episodes.id", ondelete="CASCADE"), nullable=False
    )
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("episode_script_turns.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    script_snapshot_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    referenced_skill_ids_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The model's reasoning trace for this turn, bounded by
    # `copywriter.MAX_THINKING_LEN` before it lands here — a relational
    # trace column, not backfilled for turns written before it existed
    # (those just read back as the empty-string default). Never populated
    # for a turn that failed to write at all (see `stream_new_script`'s
    # `parse_ok=False` early return): there is no turn row for it to attach
    # to, and thinking is not kept anywhere else on that path either.
    thinking_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        UniqueConstraint("episode_id", "turn_no", name="uq_episode_script_turns_episode_turn"),
        Index("ix_episode_script_turns_episode_id", "episode_id"),
    )


class CutRevision(Base):
    """Immutable timeline snapshot. Mutation always inserts a new row."""

    __tablename__ = "cut_revisions"

    id: Mapped[str] = id_column("crv")
    cut_id: Mapped[str] = mapped_column(
        ForeignKey("episode_cuts.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("cut_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    engine: Mapped[str] = mapped_column(String(40), default="zaolang-canonical", nullable=False)
    engine_schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    document_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    asset_bindings_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    duration_ticks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    command_summary_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("cut_id", "revision_no", name="uq_cut_revisions_cut_revision"),
        UniqueConstraint("cut_id", "content_hash", name="uq_cut_revisions_cut_hash"),
        Index("ix_cut_revisions_cut_id", "cut_id"),
    )


class EditPlan(Base, TimestampMixin):
    __tablename__ = "edit_plans"

    id: Mapped[str] = id_column("epl")
    cut_id: Mapped[str] = mapped_column(
        ForeignKey("episode_cuts.id", ondelete="CASCADE"), nullable=False
    )
    base_revision_id: Mapped[str] = mapped_column(
        ForeignKey("cut_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default=EditPlanStatus.GENERATING, nullable=False
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    commands_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    validation_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    warnings_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_slot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        Index("ix_edit_plans_cut_id", "cut_id"),
        Index("ix_edit_plans_base_revision_id", "base_revision_id"),
    )


class DeliveryVariant(Base, TimestampMixin):
    __tablename__ = "delivery_variants"

    id: Mapped[str] = id_column("dvr")
    cut_revision_id: Mapped[str] = mapped_column(
        ForeignKey("cut_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_num: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    fps_den: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="mp4", nullable=False)
    caption_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    caption_mode: Mapped[str] = mapped_column(String(16), default="burned", nullable=False)
    brand_pack_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    spec_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=DeliveryVariantStatus.READY, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("cut_revision_id", "spec_hash", name="uq_delivery_variants_revision_spec"),
        Index("ix_delivery_variants_cut_revision_id", "cut_revision_id"),
    )


class EditorExport(Base, TimestampMixin):
    __tablename__ = "editor_exports"

    id: Mapped[str] = id_column("exp")
    variant_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_variants.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default=EditorExportStatus.QUEUED, nullable=False
    )
    operation_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    claimed_by_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    runner_instance_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("variant_id", "operation_key", name="uq_editor_exports_variant_operation"),
        Index("ix_editor_exports_variant_id", "variant_id"),
        Index("ix_editor_exports_status", "status"),
    )


class MediaAnalysis(Base, TimestampMixin):
    __tablename__ = "media_analyses"

    id: Mapped[str] = id_column("man")
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    analyzer: Mapped[str] = mapped_column(String(40), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=MediaAnalysisStatus.QUEUED, nullable=False
    )
    transcript_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    shots_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    focus_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    audio_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    duration_ticks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "analyzer", "analyzer_version", name="uq_media_analyses_asset_analyzer"
        ),
        Index("ix_media_analyses_asset_id", "asset_id"),
    )


class EditorLease(Base, TimestampMixin):
    __tablename__ = "editor_leases"

    id: Mapped[str] = id_column("els")
    cut_id: Mapped[str] = mapped_column(
        ForeignKey("episode_cuts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    browser_instance_id: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_editor_leases_cut_id", "cut_id"),
        Index("ix_editor_leases_user_id", "user_id"),
        UniqueConstraint("token_hash", name="uq_editor_leases_token_hash"),
        Index(
            "uq_editor_leases_active_cut",
            "cut_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class EditorCommandEvent(Base):
    __tablename__ = "editor_command_events"

    id: Mapped[str] = id_column("ece")
    lease_id: Mapped[str] = mapped_column(
        ForeignKey("editor_leases.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_id: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    commands_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=EditorCommandEventStatus.APPLIED, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("lease_id", "sequence", name="uq_editor_command_events_lease_seq"),
        UniqueConstraint("batch_id", name="uq_editor_command_events_batch"),
        Index("ix_editor_command_events_lease_id", "lease_id"),
    )


class EditorOperationEvent(Base):
    """Gapless SSE log for long editor operations (plans, exports, analysis)."""

    __tablename__ = "editor_operation_events"

    id: Mapped[str] = id_column("eoe")
    operation_id: Mapped[str] = mapped_column(String(40), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    public_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "operation_id", "sequence", name="uq_editor_operation_events_operation_seq"
        ),
        Index("ix_editor_operation_events_operation_id", "operation_id"),
    )


class McpTokenGrant(Base, TimestampMixin):
    """Project-scoped MCP access. Independent of consumer/admin audiences."""

    __tablename__ = "mcp_token_grants"

    id: Mapped[str] = id_column("mtg")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    series_id: Mapped[str] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(80), nullable=False)
    jti: Mapped[str] = mapped_column(String(40), nullable=False)
    scopes_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("jti", name="uq_mcp_token_grants_jti"),
        Index("ix_mcp_token_grants_user_id", "user_id"),
        Index("ix_mcp_token_grants_series_id", "series_id"),
    )
