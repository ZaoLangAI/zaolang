"""add agent_profiles.default_for_asset_kind

Revision ID: e7f1a4b8c3d6
Revises: d4e8f1a5b9c2
Create Date: 2026-08-16 12:00:00.000000+00:00

Lets one `copy`-role `AgentProfile` be the default agent "AI 润色" routes to
for a given `ImageAssetKind` (`character`/`scene`/`cover`) — see
`app.domain.agent_skills.service.default_profile_for_asset_kind`. Nullable,
no backfill: every existing profile keeps falling back to the role's
ordinary `is_default` agent until an operator (or the seed script) opts one
in per kind. Uniqueness per `(role, kind)` is enforced in the service layer,
the same way `is_default` is, rather than by a partial index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f1a4b8c3d6"
down_revision: str | None = "d4e8f1a5b9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_profiles",
        sa.Column("default_for_asset_kind", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_profiles", "default_for_asset_kind")
