"""add canvas projects, nodes, edges, the change feed and agent runs

Revision ID: a7f2c4d9e310
Revises: c4d8e1f2a6b0
Create Date: 2026-09-03 09:00:00.000000+00:00

The infinite canvas's store. `series_id` on `canvas_projects` is nullable and
is the only thing distinguishing the two modes: set = drama mode (cards bind to
episodes / shots / skills / drafts), NULL = free sandbox. The unique index on
it is therefore partial - one canvas per series, unlimited free canvases.

Cards and connections are rows rather than one JSON document because an Agent
run lands a generated result asynchronously, from a worker, while the browser
is autosaving layout. One JSON column gives those two writers a single cell to
fight over; rows let the worker INSERT and the browser UPDATE without ever
touching the same row. `canvas_projects.change_seq` orders every write (it is
allocated under the project row's lock and never rejects a writer), and
`canvas_changes` is the durable log that makes `?since=N` catch-up and SSE
resume possible - a deleted row cannot carry its own tombstone.

`canvas_agent_runs` / `canvas_agent_tasks` sit above `generation_jobs`: an Agent
run plans, the user confirms, and each planned generation is submitted through
the ordinary pipeline so credits, routing and moderation all still apply. The
join back from a finished job is an index on `canvas_agent_tasks`, not a column
on `generation_jobs` — that table should stop growing a nullable pointer per
consuming surface.

There is deliberately no lease table: `EditorLease` is single-writer and scoped
to one `EpisodeCut`, whereas a canvas spans many cuts or none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7f2c4d9e310"
down_revision: str | None = "c4d8e1f2a6b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "canvas_projects",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_user_id", sa.String(length=40), nullable=False),
        sa.Column("series_id", sa.String(length=40), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("viewport_json", _jsonb(), nullable=False),
        sa.Column("change_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=40), nullable=True),
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
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_canvas_projects_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_canvas_projects_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_canvas_projects_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_projects")),
    )
    op.create_index(
        "ix_canvas_projects_owner_user_id", "canvas_projects", ["owner_user_id"], unique=False
    )
    op.create_index(
        "uq_canvas_projects_series",
        "canvas_projects",
        ["series_id"],
        unique=True,
        postgresql_where=sa.text("series_id IS NOT NULL"),
    )

    op.create_table(
        "canvas_nodes",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("canvas_id", sa.String(length=40), nullable=False),
        sa.Column("node_kind", sa.String(length=32), nullable=False),
        sa.Column("position_x", sa.Integer(), nullable=False),
        sa.Column("position_y", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("z_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("binding_asset_id", sa.String(length=40), nullable=True),
        sa.Column("binding_skill_id", sa.String(length=40), nullable=True),
        sa.Column("binding_json", _jsonb(), nullable=False),
        sa.Column("data_json", _jsonb(), nullable=False),
        sa.Column("origin", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=40), nullable=True),
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
            ["canvas_id"],
            ["canvas_projects.id"],
            name=op.f("fk_canvas_nodes_canvas_id_canvas_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_canvas_nodes_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_canvas_nodes_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_nodes")),
    )
    op.create_index("ix_canvas_nodes_canvas_id_seq", "canvas_nodes", ["canvas_id", "seq"])
    op.create_index(
        "ix_canvas_nodes_canvas_id_binding_asset_id",
        "canvas_nodes",
        ["canvas_id", "binding_asset_id"],
        postgresql_where=sa.text("binding_asset_id IS NOT NULL"),
    )
    op.create_index(
        "ix_canvas_nodes_canvas_id_binding_skill_id",
        "canvas_nodes",
        ["canvas_id", "binding_skill_id"],
        postgresql_where=sa.text("binding_skill_id IS NOT NULL"),
    )

    op.create_table(
        "canvas_edges",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("canvas_id", sa.String(length=40), nullable=False),
        sa.Column("source_node_id", sa.String(length=40), nullable=False),
        sa.Column("target_node_id", sa.String(length=40), nullable=False),
        sa.Column("source_handle", sa.String(length=40), server_default="", nullable=False),
        sa.Column("target_handle", sa.String(length=40), server_default="", nullable=False),
        sa.Column("edge_kind", sa.String(length=32), server_default="link", nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=True),
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
            ["canvas_id"],
            ["canvas_projects.id"],
            name=op.f("fk_canvas_edges_canvas_id_canvas_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["canvas_nodes.id"],
            name=op.f("fk_canvas_edges_source_node_id_canvas_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["canvas_nodes.id"],
            name=op.f("fk_canvas_edges_target_node_id_canvas_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_canvas_edges_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_edges")),
        sa.UniqueConstraint(
            "canvas_id",
            "source_node_id",
            "target_node_id",
            "source_handle",
            "target_handle",
            name="uq_canvas_edges_endpoints",
        ),
    )
    op.create_index(
        "ix_canvas_edges_canvas_id_target_node_id", "canvas_edges", ["canvas_id", "target_node_id"]
    )
    op.create_index(
        "ix_canvas_edges_canvas_id_source_node_id", "canvas_edges", ["canvas_id", "source_node_id"]
    )
    op.create_index("ix_canvas_edges_canvas_id_seq", "canvas_edges", ["canvas_id", "seq"])

    op.create_table(
        "canvas_changes",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("canvas_id", sa.String(length=40), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.String(length=40), nullable=True),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id"],
            ["canvas_projects.id"],
            name=op.f("fk_canvas_changes_canvas_id_canvas_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_changes")),
        sa.UniqueConstraint("canvas_id", "seq", name="uq_canvas_changes_canvas_seq"),
    )

    op.create_table(
        "canvas_agent_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("canvas_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="planning", nullable=False),
        sa.Column("origin", sa.String(length=16), server_default="agent", nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("agent_node_id", sa.String(length=40), nullable=True),
        sa.Column("context_node_ids_json", _jsonb(), nullable=False),
        sa.Column("context_digest_json", _jsonb(), nullable=False),
        sa.Column("plan_json", _jsonb(), nullable=False),
        sa.Column("planner_agent_run_id", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("quoted_credits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_credits", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
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
            ["canvas_id"],
            ["canvas_projects.id"],
            name=op.f("fk_canvas_agent_runs_canvas_id_canvas_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_canvas_agent_runs_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_node_id"],
            ["canvas_nodes.id"],
            name=op.f("fk_canvas_agent_runs_agent_node_id_canvas_nodes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_agent_runs")),
    )
    op.create_index(
        "ix_canvas_agent_runs_canvas_id_created_at",
        "canvas_agent_runs",
        ["canvas_id", "created_at"],
    )

    op.create_table(
        "canvas_agent_tasks",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("quality_tier", sa.String(length=24), nullable=False),
        sa.Column("request_json", _jsonb(), nullable=False),
        sa.Column("generation_job_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="planned", nullable=False),
        sa.Column("drop_x", sa.Integer(), nullable=False),
        sa.Column("drop_y", sa.Integer(), nullable=False),
        sa.Column("result_node_id", sa.String(length=40), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
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
            ["run_id"],
            ["canvas_agent_runs.id"],
            name=op.f("fk_canvas_agent_tasks_run_id_canvas_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            name=op.f("fk_canvas_agent_tasks_generation_job_id_generation_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_node_id"],
            ["canvas_nodes.id"],
            name=op.f("fk_canvas_agent_tasks_result_node_id_canvas_nodes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_agent_tasks")),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_canvas_agent_tasks_run_ordinal"),
    )
    op.create_index(
        "ix_canvas_agent_tasks_generation_job_id", "canvas_agent_tasks", ["generation_job_id"]
    )
    op.create_index(
        "ix_canvas_agent_tasks_run_id_ordinal", "canvas_agent_tasks", ["run_id", "ordinal"]
    )


def downgrade() -> None:
    op.drop_index("ix_canvas_agent_tasks_run_id_ordinal", table_name="canvas_agent_tasks")
    op.drop_index("ix_canvas_agent_tasks_generation_job_id", table_name="canvas_agent_tasks")
    op.drop_table("canvas_agent_tasks")
    op.drop_index("ix_canvas_agent_runs_canvas_id_created_at", table_name="canvas_agent_runs")
    op.drop_table("canvas_agent_runs")
    op.drop_table("canvas_changes")
    op.drop_index("ix_canvas_edges_canvas_id_seq", table_name="canvas_edges")
    op.drop_index("ix_canvas_edges_canvas_id_source_node_id", table_name="canvas_edges")
    op.drop_index("ix_canvas_edges_canvas_id_target_node_id", table_name="canvas_edges")
    op.drop_table("canvas_edges")
    op.drop_index("ix_canvas_nodes_canvas_id_binding_skill_id", table_name="canvas_nodes")
    op.drop_index("ix_canvas_nodes_canvas_id_binding_asset_id", table_name="canvas_nodes")
    op.drop_index("ix_canvas_nodes_canvas_id_seq", table_name="canvas_nodes")
    op.drop_table("canvas_nodes")
    op.drop_index("uq_canvas_projects_series", table_name="canvas_projects")
    op.drop_index("ix_canvas_projects_owner_user_id", table_name="canvas_projects")
    op.drop_table("canvas_projects")
