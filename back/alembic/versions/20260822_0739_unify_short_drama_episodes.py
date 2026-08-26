"""unify short drama episodes

Gives every `Series` (not just `kind=drama`) a first-class episode entity to
attach content to, ahead of the short-drama workspace's episode-centric
redesign:

1. `drama_episodes` gains `season_number` (default 1) and `episode_kind`
   (default `main` — see `EpisodeKind`); uniqueness widens from
   `(series_id, episode_number)` to `(series_id, season_number,
   episode_number)` so a trailer or a season 2 opener never collides with
   season 1 episode 1.
2. A new `episode_content_links` table records material (a script/image/
   video draft, a published `Work`, an `EditorExport`) associated with an
   episode without being its canonical output — see `EpisodeContentLink`.
3. Backfills a `DramaEpisode` row for every `(series_id, episode_number)`
   pair that already exists purely as a tag on a published `Work`
   (`Work.series_id`/`episode_number`, written by
   `characters.service.assign_episode` for `kind=cast` series today) — so
   the pre-existing lightweight tagging is visible in the new model too,
   with `canonical_work_id` pointing at the `Work` that carried the tag.
   `kind=drama` series already have their own `DramaEpisode` rows and are
   left untouched (the join below only looks at `works`, never
   `drama_episodes`, but still skips a pair if a matching episode already
   exists, so a rerun — or a series that happens to have both — is a no-op).

Does not touch `Series.kind` or the `/v1/series` vs `/v1/drama-series`
route isolation — see `zaolang-editor-drama`. This migration only makes the
*episode* underneath series-agnostic; ownership/isolation for the *series*
resource itself is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import new_id

revision: str = "9af5e04a2bba"
down_revision: str | None = "a9d4c7e2f8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "episode_content_links",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("episode_id", sa.String(length=40), nullable=False),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("content_ref_id", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["drama_episodes.id"],
            name=op.f("fk_episode_content_links_episode_id_drama_episodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_content_links")),
        sa.UniqueConstraint(
            "episode_id",
            "content_type",
            "content_ref_id",
            name="uq_episode_content_links_episode_content",
        ),
    )
    op.create_index(
        "ix_episode_content_links_episode_id", "episode_content_links", ["episode_id"], unique=False
    )

    op.add_column(
        "drama_episodes",
        sa.Column("season_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "drama_episodes",
        sa.Column("episode_kind", sa.String(length=16), server_default="main", nullable=False),
    )
    op.drop_constraint(op.f("uq_drama_episodes_series_number"), "drama_episodes", type_="unique")
    op.create_unique_constraint(
        "uq_drama_episodes_series_season_number",
        "drama_episodes",
        ["series_id", "season_number", "episode_number"],
    )

    _backfill_episodes_from_tagged_works()


def _backfill_episodes_from_tagged_works() -> None:
    bind = op.get_bind()
    pairs = (
        bind.execute(
            sa.text(
                "SELECT w.series_id, w.episode_number, w.id AS work_id, wv.title, "
                "w.lifecycle_status "
                "FROM works w "
                "LEFT JOIN work_versions wv ON wv.id = w.current_version_id "
                "WHERE w.series_id IS NOT NULL AND w.episode_number IS NOT NULL "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM drama_episodes de "
                "  WHERE de.series_id = w.series_id AND de.season_number = 1 "
                "  AND de.episode_number = w.episode_number"
                ") "
                # A series can tag more than one Work under the same episode
                # number in theory (the DB has no constraint stopping it);
                # picking the most recently published one keeps this
                # deterministic instead of racing on row order.
                "ORDER BY w.series_id, w.episode_number, w.published_at DESC NULLS LAST"
            )
        )
        .mappings()
        .all()
    )
    seen: set[tuple[str, int]] = set()
    for row in pairs:
        key = (row["series_id"], row["episode_number"])
        if key in seen:
            continue
        seen.add(key)
        status = "published" if row["lifecycle_status"] == "active" else "archived"
        bind.execute(
            sa.text(
                "INSERT INTO drama_episodes "
                "(id, series_id, season_number, episode_number, episode_kind, title, "
                "synopsis, script_json, status, canonical_work_id, created_at, updated_at) "
                "VALUES (:id, :series_id, 1, :episode_number, 'main', :title, NULL, "
                "'{}'::jsonb, :status, :work_id, now(), now())"
            ).bindparams(
                id=new_id("dep"),
                series_id=row["series_id"],
                episode_number=row["episode_number"],
                title=(row["title"] or f"第 {row['episode_number']} 集")[:200],
                status=status,
                work_id=row["work_id"],
            )
        )


def downgrade() -> None:
    # The backfilled rows are indistinguishable from a manually-created
    # episode by the time downgrade could run — nothing sound to reverse
    # there, same reasoning as `20260816_1000_merge_character_views`'s
    # downgrade. Only the schema changes are reversible.
    op.drop_constraint("uq_drama_episodes_series_season_number", "drama_episodes", type_="unique")
    op.create_unique_constraint(
        op.f("uq_drama_episodes_series_number"), "drama_episodes", ["series_id", "episode_number"]
    )
    op.drop_column("drama_episodes", "episode_kind")
    op.drop_column("drama_episodes", "season_number")
    op.drop_index("ix_episode_content_links_episode_id", table_name="episode_content_links")
    op.drop_table("episode_content_links")
