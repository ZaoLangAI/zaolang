"""add workflow template asset_kind

Adds the `asset_kind` dimension so `text_to_image`/`image_to_image` can carry
more than one active `GenerationWorkflowTemplate` at a time — one generic
(`asset_kind IS NULL`) plus one per non-`GENERAL` `ImageAssetKind`
(character view / scene / cover). See `app.models.enums.ImageAssetKind` and
`app.domain.workflow_templates.service.get_active`.

Revision ID: d9e4f7a2b6c3
Revises: f3a8c92b7e14
Create Date: 2026-08-15 20:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e4f7a2b6c3"
down_revision: str | None = "f3a8c92b7e14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_workflow_templates", sa.Column("asset_kind", sa.String(length=32), nullable=True)
    )
    op.drop_constraint(
        "uq_generation_workflow_templates_op_version",
        "generation_workflow_templates",
        type_="unique",
    )
    op.drop_index(
        "ix_generation_workflow_templates_operation_active",
        table_name="generation_workflow_templates",
    )
    op.create_unique_constraint(
        "uq_generation_workflow_templates_op_kind_version",
        "generation_workflow_templates",
        ["operation", "asset_kind", "version"],
    )
    op.create_index(
        "ix_generation_workflow_templates_operation_kind_active",
        "generation_workflow_templates",
        ["operation", "asset_kind", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generation_workflow_templates_operation_kind_active",
        table_name="generation_workflow_templates",
    )
    op.drop_constraint(
        "uq_generation_workflow_templates_op_kind_version",
        "generation_workflow_templates",
        type_="unique",
    )
    # Rows with a non-null `asset_kind` collide with the restored
    # `(operation, version)` uniqueness; a downgrade only makes sense before
    # any such row was ever published, so they are dropped rather than
    # renumbered.
    op.execute(sa.text("DELETE FROM generation_workflow_templates WHERE asset_kind IS NOT NULL"))
    op.create_index(
        "ix_generation_workflow_templates_operation_active",
        "generation_workflow_templates",
        ["operation", "is_active"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_generation_workflow_templates_op_version",
        "generation_workflow_templates",
        ["operation", "version"],
    )
    op.drop_column("generation_workflow_templates", "asset_kind")
