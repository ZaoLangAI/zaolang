"""repair canvas row tables after a stamped revision drifted

Revision ID: d4e8b2c6a170
Revises: c3d8a1b5e920
Create Date: 2026-09-09 22:30:00.000000+00:00

`a7f2c4d9e310` is the six-table row store. A production database that was
stamped at that revision while the file still only created a JSON
`canvas_projects` (graph_json / revision) never grew `canvas_nodes` /
`canvas_edges` / `canvas_changes` / `canvas_agent_runs` /
`canvas_agent_tasks`, and never grew `viewport_json` / `change_seq`. Later
heads (`b8c4e6a2d710`, `c3d8a1b5e920`) were applied on top, so `upgrade
head` would not re-run `a7f2c4d9e310`.

This revision is the repair: inspect, then add only what is missing. Old
`graph_json` / `revision` columns stay — three historical rows still use
them, and the current ORM does not read them. Downgrade is a no-op: this
must not drop tables a healthy database already received from
`a7f2c4d9e310`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "d4e8b2c6a170"
down_revision: str | None = "c3d8a1b5e920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _bind() -> Connection:
    return op.get_bind()


def _tables() -> set[str]:
    return set(sa_inspect(_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa_inspect(_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    inspector = sa_inspect(_bind())
    names = {index["name"] for index in inspector.get_indexes(table) if index["name"]}
    names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
        if constraint["name"]
    )
    return names


def _ensure_index(
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
    postgresql_where: sa.TextClause | None = None,
) -> None:
    if name in _index_names(table):
        return
    kwargs: dict[str, object] = {"unique": unique}
    if postgresql_where is not None:
        kwargs["postgresql_where"] = postgresql_where
    op.create_index(name, table, columns, **kwargs)


def _create_canvas_projects() -> None:
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
    _ensure_canvas_projects_indexes()


def _repair_canvas_projects() -> None:
    columns = _columns("canvas_projects")
    if "viewport_json" not in columns:
        op.add_column(
            "canvas_projects",
            sa.Column(
                "viewport_json",
                _jsonb(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
        # Match the original revision / ORM: no permanent server_default.
        op.alter_column("canvas_projects", "viewport_json", server_default=None)
    if "change_seq" not in columns:
        op.add_column(
            "canvas_projects",
            sa.Column(
                "change_seq",
                sa.BigInteger(),
                server_default="0",
                nullable=False,
            ),
        )
    _ensure_canvas_projects_indexes()


def _ensure_canvas_projects_indexes() -> None:
    _ensure_index("ix_canvas_projects_owner_user_id", "canvas_projects", ["owner_user_id"])
    _ensure_index(
        "uq_canvas_projects_series",
        "canvas_projects",
        ["series_id"],
        unique=True,
        postgresql_where=sa.text("series_id IS NOT NULL"),
    )


def _create_canvas_nodes() -> None:
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
    _ensure_canvas_nodes_indexes()


def _ensure_canvas_nodes_indexes() -> None:
    _ensure_index("ix_canvas_nodes_canvas_id_seq", "canvas_nodes", ["canvas_id", "seq"])
    _ensure_index(
        "ix_canvas_nodes_canvas_id_binding_asset_id",
        "canvas_nodes",
        ["canvas_id", "binding_asset_id"],
        postgresql_where=sa.text("binding_asset_id IS NOT NULL"),
    )
    _ensure_index(
        "ix_canvas_nodes_canvas_id_binding_skill_id",
        "canvas_nodes",
        ["canvas_id", "binding_skill_id"],
        postgresql_where=sa.text("binding_skill_id IS NOT NULL"),
    )


def _create_canvas_edges() -> None:
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
    _ensure_canvas_edges_indexes()


def _ensure_canvas_edges_indexes() -> None:
    _ensure_index(
        "ix_canvas_edges_canvas_id_target_node_id",
        "canvas_edges",
        ["canvas_id", "target_node_id"],
    )
    _ensure_index(
        "ix_canvas_edges_canvas_id_source_node_id",
        "canvas_edges",
        ["canvas_id", "source_node_id"],
    )
    _ensure_index("ix_canvas_edges_canvas_id_seq", "canvas_edges", ["canvas_id", "seq"])


def _create_canvas_changes() -> None:
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


def _create_canvas_agent_runs() -> None:
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
    _ensure_canvas_agent_runs_indexes()


def _ensure_canvas_agent_runs_indexes() -> None:
    _ensure_index(
        "ix_canvas_agent_runs_canvas_id_created_at",
        "canvas_agent_runs",
        ["canvas_id", "created_at"],
    )


def _create_canvas_agent_tasks() -> None:
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
    _ensure_canvas_agent_tasks_indexes()


def _ensure_canvas_agent_tasks_indexes() -> None:
    _ensure_index(
        "ix_canvas_agent_tasks_generation_job_id",
        "canvas_agent_tasks",
        ["generation_job_id"],
    )
    _ensure_index(
        "ix_canvas_agent_tasks_run_id_ordinal",
        "canvas_agent_tasks",
        ["run_id", "ordinal"],
    )


def upgrade() -> None:
    tables = _tables()
    if "canvas_projects" in tables:
        _repair_canvas_projects()
    else:
        _create_canvas_projects()

    if "canvas_nodes" not in tables:
        _create_canvas_nodes()
    else:
        _ensure_canvas_nodes_indexes()

    if "canvas_edges" not in tables:
        _create_canvas_edges()
    else:
        _ensure_canvas_edges_indexes()

    if "canvas_changes" not in tables:
        _create_canvas_changes()

    if "canvas_agent_runs" not in tables:
        _create_canvas_agent_runs()
    else:
        _ensure_canvas_agent_runs_indexes()

    if "canvas_agent_tasks" not in tables:
        _create_canvas_agent_tasks()
    else:
        _ensure_canvas_agent_tasks_indexes()


def downgrade() -> None:
    # Repair only. A healthy database already has these objects from
    # a7f2c4d9e310; dropping them here would destroy live canvas rows.
    return
