"""add trigram indexes for work search

Revision ID: 2bdefd8d370f
Revises: 23b7404b3ff1
Create Date: 2026-08-29 08:53:31.836064+00:00

`pg_trgm` (enabled since the initial schema, but never used by an index) lets
a GIN index serve a leading-wildcard `LIKE '%...%'` — the exact shape
`search.service._keyword_search` already runs. Each index is functional and
must match its query's expression byte-for-byte to be used: `lower(title)`
and `lower(description)` (a plain column reference, not
`lower(coalesce(description, ''))` — see the comment in `_keyword_search`
for why the query is written to match).

Not modelled in `WorkVersion.__table_args__`: SQLAlchemy's declarative layer
has no clean way to express a functional GIN index, and autogenerate cannot
introspect one either — the partial unique index on `editor_leases` set the
precedent for a migration-only index invisible to the ORM.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2bdefd8d370f"
down_revision: str | None = "23b7404b3ff1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_work_versions_title_trgm ON work_versions "
        "USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_work_versions_description_trgm ON work_versions "
        "USING gin (lower(description) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_work_versions_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_work_versions_title_trgm")
