"""scene panorama entry type (AC-7)

A scene variant may hold one 360° equirectangular still
(`entry_type='panorama'`), which the `skill_asset_entries` `entry_type_valid`
CHECK must now allow. Autogenerate does not see CHECK changes, hence by hand.

Revision ID: 3e9a7c5d1f20
Revises: 8c2f6d1b7e43
Create Date: 2026-10-08 10:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "3e9a7c5d1f20"
down_revision: str | None = "8c2f6d1b7e43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_skill_asset_entries_entry_type_valid"
_BEFORE = (
    "identity_portrait",
    "character_sheet",
    "view",
    "expression_sheet",
    "pose",
    "outfit_detail",
    "prop",
    "master",
    "shot",
    "other",
)
_AFTER = (*_BEFORE[:9], "panorama", "other")


def _condition(types: tuple[str, ...]) -> str:
    return "entry_type IN ({})".format(", ".join(f"'{t}'" for t in types))


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "skill_asset_entries", type_="check")
    op.create_check_constraint(op.f(CHECK), "skill_asset_entries", _condition(_AFTER))


def downgrade() -> None:
    # A panorama has no older type to fall back to (it is no reference), so
    # its entries go; the image assets themselves stay.
    op.execute("DELETE FROM skill_asset_entries WHERE entry_type = 'panorama'")
    op.drop_constraint(op.f(CHECK), "skill_asset_entries", type_="check")
    op.create_check_constraint(op.f(CHECK), "skill_asset_entries", _condition(_BEFORE))
