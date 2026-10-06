"""prop assets (AC-4)

道具 cards are `creation_skills` rows with `category='prop_asset'` (a plain
string column, no migration); their variants are `skill_asset_variants`
with `kind='prop_variant'`, which the `kind_valid` CHECK must now allow.
`generation_jobs.linked_prop_id` mirrors `linked_character_id` /
`linked_scene_id` (no FK — see `20260817_1000_add_generation_job_linked_ids`).

Revision ID: 8c2f6d1b7e43
Revises: 5b7e2c4a9d10
Create Date: 2026-10-07 11:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8c2f6d1b7e43"
down_revision: str | None = "5b7e2c4a9d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_skill_asset_variants_kind_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "skill_asset_variants", type_="check")
    op.create_check_constraint(
        op.f(CHECK), "skill_asset_variants", "kind IN ('look', 'scene_variant', 'prop_variant')"
    )
    op.add_column("generation_jobs", sa.Column("linked_prop_id", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_jobs", "linked_prop_id")
    op.execute("DELETE FROM skill_asset_variants WHERE kind = 'prop_variant'")
    op.drop_constraint(op.f(CHECK), "skill_asset_variants", type_="check")
    op.create_check_constraint(
        op.f(CHECK), "skill_asset_variants", "kind IN ('look', 'scene_variant')"
    )
