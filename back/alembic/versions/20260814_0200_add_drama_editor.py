"""add drama editor tables and series production columns

Revision ID: a7b8c9d0e1f2
Revises: f1a2c3d4e5f6
Create Date: 2026-08-14 02:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "series",
        sa.Column("kind", sa.String(length=16), server_default="cast", nullable=False),
    )
    op.add_column(
        "series",
        sa.Column("default_locale", sa.String(length=16), server_default="zh-CN", nullable=False),
    )
    op.add_column(
        "series",
        sa.Column("brand_pack_asset_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "series",
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.add_column(
        "series",
        sa.Column(
            "allow_external_models",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_series_brand_pack_asset_id_assets"),
        "series",
        "assets",
        ["brand_pack_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_series_owner_user_id_kind", "series", ["owner_user_id", "kind"])
    op.alter_column("series", "kind", server_default=None)
    op.alter_column("series", "default_locale", server_default=None)
    op.alter_column("series", "status", server_default=None)
    op.alter_column("series", "allow_external_models", server_default=None)

    op.create_table(
        "drama_episodes",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("synopsis", sa.Text(), nullable=True),
        sa.Column(
            "script_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("canonical_work_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["series.id"], name=op.f("fk_drama_episodes_series_id_series"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["canonical_work_id"],
            ["works.id"],
            name=op.f("fk_drama_episodes_canonical_work_id_works"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drama_episodes")),
        sa.UniqueConstraint("series_id", "episode_number", name="uq_drama_episodes_series_number"),
    )
    op.create_index("ix_drama_episodes_series_id", "drama_episodes", ["series_id"])

    op.create_table(
        "episode_cuts",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("episode_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("head_revision_id", sa.String(length=40), nullable=True),
        sa.Column("base_cut_id", sa.String(length=40), nullable=True),
        sa.Column("source_asset_id", sa.String(length=40), nullable=True),
        sa.Column("source_job_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["drama_episodes.id"],
            name=op.f("fk_episode_cuts_episode_id_drama_episodes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_cut_id"],
            ["episode_cuts.id"],
            name=op.f("fk_episode_cuts_base_cut_id_episode_cuts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["assets.id"],
            name=op.f("fk_episode_cuts_source_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_cuts")),
        sa.UniqueConstraint("episode_id", "kind", "name", name="uq_episode_cuts_episode_kind_name"),
    )
    op.create_index("ix_episode_cuts_episode_id", "episode_cuts", ["episode_id"])

    op.create_table(
        "cut_revisions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("cut_id", sa.String(length=40), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=40), nullable=True),
        sa.Column("engine", sa.String(length=40), nullable=False),
        sa.Column("engine_schema_version", sa.Integer(), nullable=False),
        sa.Column("document_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("asset_bindings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ticks", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("command_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cut_id"],
            ["episode_cuts.id"],
            name=op.f("fk_cut_revisions_cut_id_episode_cuts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["cut_revisions.id"],
            name=op.f("fk_cut_revisions_parent_revision_id_cut_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_cut_revisions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cut_revisions")),
        sa.UniqueConstraint("cut_id", "revision_no", name="uq_cut_revisions_cut_revision"),
        sa.UniqueConstraint("cut_id", "content_hash", name="uq_cut_revisions_cut_hash"),
    )
    op.create_index("ix_cut_revisions_cut_id", "cut_revisions", ["cut_id"])

    op.create_table(
        "edit_plans",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("cut_id", sa.String(length=40), nullable=False),
        sa.Column("base_revision_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("commands_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diff_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_run_id", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_slot", sa.String(length=40), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("applied_revision_id", sa.String(length=40), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cut_id"], ["episode_cuts.id"], name=op.f("fk_edit_plans_cut_id_episode_cuts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["base_revision_id"],
            ["cut_revisions.id"],
            name=op.f("fk_edit_plans_base_revision_id_cut_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_edit_plans_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edit_plans")),
    )
    op.create_index("ix_edit_plans_cut_id", "edit_plans", ["cut_id"])
    op.create_index("ix_edit_plans_base_revision_id", "edit_plans", ["base_revision_id"])

    op.create_table(
        "delivery_variants",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("cut_revision_id", sa.String(length=40), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=16), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps_num", sa.Integer(), nullable=False),
        sa.Column("fps_den", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("caption_language", sa.String(length=16), nullable=True),
        sa.Column("caption_mode", sa.String(length=16), nullable=False),
        sa.Column("brand_pack_id", sa.String(length=40), nullable=True),
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cut_revision_id"],
            ["cut_revisions.id"],
            name=op.f("fk_delivery_variants_cut_revision_id_cut_revisions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_variants")),
        sa.UniqueConstraint("cut_revision_id", "spec_hash", name="uq_delivery_variants_revision_spec"),
    )
    op.create_index("ix_delivery_variants_cut_revision_id", "delivery_variants", ["cut_revision_id"])

    op.create_table(
        "editor_exports",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("variant_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("operation_key", sa.String(length=80), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("claimed_by_user_id", sa.String(length=40), nullable=True),
        sa.Column("runner_instance_id", sa.String(length=80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("output_asset_id", sa.String(length=40), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["delivery_variants.id"],
            name=op.f("fk_editor_exports_variant_id_delivery_variants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["output_asset_id"],
            ["assets.id"],
            name=op.f("fk_editor_exports_output_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_exports")),
        sa.UniqueConstraint("variant_id", "operation_key", name="uq_editor_exports_variant_operation"),
    )
    op.create_index("ix_editor_exports_variant_id", "editor_exports", ["variant_id"])
    op.create_index("ix_editor_exports_status", "editor_exports", ["status"])

    op.create_table(
        "media_analyses",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("asset_id", sa.String(length=40), nullable=False),
        sa.Column("analyzer", sa.String(length=40), nullable=False),
        sa.Column("analyzer_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("transcript_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("shots_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("focus_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audio_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ticks", sa.BigInteger(), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_media_analyses_asset_id_assets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_analyses")),
        sa.UniqueConstraint(
            "asset_id", "analyzer", "analyzer_version", name="uq_media_analyses_asset_analyzer"
        ),
    )
    op.create_index("ix_media_analyses_asset_id", "media_analyses", ["asset_id"])

    op.create_table(
        "editor_leases",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("cut_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("browser_instance_id", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("base_revision_id", sa.String(length=40), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cut_id"], ["episode_cuts.id"], name=op.f("fk_editor_leases_cut_id_episode_cuts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_editor_leases_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_leases")),
        sa.UniqueConstraint("token_hash", name="uq_editor_leases_token_hash"),
    )
    op.create_index("ix_editor_leases_cut_id", "editor_leases", ["cut_id"])
    op.create_index("ix_editor_leases_user_id", "editor_leases", ["user_id"])

    op.create_table(
        "editor_command_events",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("lease_id", sa.String(length=40), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=80), nullable=False),
        sa.Column("expected_revision_id", sa.String(length=40), nullable=True),
        sa.Column("result_revision_id", sa.String(length=40), nullable=True),
        sa.Column("commands_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["editor_leases.id"],
            name=op.f("fk_editor_command_events_lease_id_editor_leases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_command_events")),
        sa.UniqueConstraint("lease_id", "sequence", name="uq_editor_command_events_lease_seq"),
        sa.UniqueConstraint("batch_id", name="uq_editor_command_events_batch"),
    )
    op.create_index("ix_editor_command_events_lease_id", "editor_command_events", ["lease_id"])

    op.create_table(
        "editor_operation_events",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("public_message", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_operation_events")),
        sa.UniqueConstraint(
            "operation_id", "sequence", name="uq_editor_operation_events_operation_seq"
        ),
    )
    op.create_index("ix_editor_operation_events_operation_id", "editor_operation_events", ["operation_id"])

    op.create_table(
        "mcp_token_grants",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=80), nullable=False),
        sa.Column("jti", sa.String(length=40), nullable=False),
        sa.Column("scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_mcp_token_grants_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["series.id"], name=op.f("fk_mcp_token_grants_series_id_series"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_token_grants")),
        sa.UniqueConstraint("jti", name="uq_mcp_token_grants_jti"),
    )
    op.create_index("ix_mcp_token_grants_user_id", "mcp_token_grants", ["user_id"])
    op.create_index("ix_mcp_token_grants_series_id", "mcp_token_grants", ["series_id"])

    op.add_column("drafts", sa.Column("source_cut_revision_id", sa.String(length=40), nullable=True))
    op.add_column("drafts", sa.Column("delivery_variant_id", sa.String(length=40), nullable=True))
    op.add_column("drafts", sa.Column("editor_export_id", sa.String(length=40), nullable=True))
    op.add_column("work_versions", sa.Column("editor_export_id", sa.String(length=40), nullable=True))
    op.add_column(
        "publication_intents", sa.Column("delivery_variant_id", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "publication_intents", sa.Column("editor_export_id", sa.String(length=40), nullable=True)
    )
    op.add_column("upload_sessions", sa.Column("bound_export_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("upload_sessions", "bound_export_id")
    op.drop_column("publication_intents", "editor_export_id")
    op.drop_column("publication_intents", "delivery_variant_id")
    op.drop_column("work_versions", "editor_export_id")
    op.drop_column("drafts", "editor_export_id")
    op.drop_column("drafts", "delivery_variant_id")
    op.drop_column("drafts", "source_cut_revision_id")
    op.drop_table("mcp_token_grants")
    op.drop_table("editor_operation_events")
    op.drop_table("editor_command_events")
    op.drop_table("editor_leases")
    op.drop_table("media_analyses")
    op.drop_table("editor_exports")
    op.drop_table("delivery_variants")
    op.drop_table("edit_plans")
    op.drop_table("cut_revisions")
    op.drop_table("episode_cuts")
    op.drop_table("drama_episodes")
    op.drop_index("ix_series_owner_user_id_kind", table_name="series")
    op.drop_constraint(op.f("fk_series_brand_pack_asset_id_assets"), "series", type_="foreignkey")
    op.drop_column("series", "allow_external_models")
    op.drop_column("series", "status")
    op.drop_column("series", "brand_pack_asset_id")
    op.drop_column("series", "default_locale")
    op.drop_column("series", "kind")
