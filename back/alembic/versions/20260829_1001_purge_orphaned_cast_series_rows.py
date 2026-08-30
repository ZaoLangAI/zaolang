"""purge orphaned cast series rows

Revision ID: ada14f32676f
Revises: dd368efe1016
Create Date: 2026-08-29 10:01:04.584902+00:00

Step ① of the `Series(kind=cast)` roster cleanup (see
`docs/performance-audit.md` §6 and `.cursor/plans/...`): the roster CRUD
(`create_series`/`list_series`/`get_series_detail`/`assign_episode`/...) was
removed with the old single-clip `ShortformStudio` it only ever served, and
every remaining `Series` creation path (`app.domain.editor.service`,
`app.domain.script_writing.service`) has explicitly passed `kind=drama` ever
since. Any `kind='cast'` row left in the table today is unreachable dead data
— there is no route left that reads or writes one — so it is safe to delete
outright rather than merely hide.

Guarded by `NOT EXISTS (... drama_episodes ...)` purely as a belt-and-braces
check against the invariant above: a cast row was never supposed to have
production episodes attached (`drama_episodes.series_id` is `ON DELETE
RESTRICT`, which would otherwise abort this migration on an unexpected row
rather than silently orphaning episodes). `works.series_id` is `ON DELETE
SET NULL` and `mcp_token_grants.series_id` is `ON DELETE CASCADE`, so both
tables tolerate the delete safely if a cast row was ever (incorrectly)
referenced by either.

Irreversible by design: a `downgrade()` cannot resurrect rows that were
never supposed to exist as live data in the first place.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "ada14f32676f"
down_revision: str | None = "dd368efe1016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    deleted = connection.execute(
        text(
            """
            DELETE FROM series
            WHERE kind = 'cast'
              AND NOT EXISTS (
                  SELECT 1 FROM drama_episodes WHERE drama_episodes.series_id = series.id
              )
            """
        )
    )
    if deleted.rowcount:
        logger.info("purged %s orphaned kind=cast series row(s)", deleted.rowcount)

    remaining = connection.execute(
        text("SELECT count(*) FROM series WHERE kind = 'cast'")
    ).scalar_one()
    if remaining:
        logger.warning(
            "%s kind=cast series row(s) still have drama_episodes attached and were "
            "left in place — investigate before the next cleanup step drops "
            "SeriesKind.CAST",
            remaining,
        )


def downgrade() -> None:
    pass
