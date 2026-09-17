"""unique character skill titles per owner

Revision ID: b8c4e6a2d710
Revises: a7f2c4d9e310
Create Date: 2026-09-04 10:49:00.000000+00:00

A character is a `CreationSkill(category=character)` whose `title` is the
library name. Two cards named "林彻" on the same account made the script
studio's "generate all character images" spawn a twin instead of reusing
the existing one. Partial unique index on `(owner_user_id, title)` for
that category only — scenes and templates may still share a title with a
character, and two owners may both have "林彻".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c4e6a2d710"
down_revision: str | None = "a7f2c4d9e310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TITLE_MAX = 80


def _rename_duplicate_character_titles() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE creation_skills
            SET title = btrim(title)
            WHERE category = 'character' AND title <> btrim(title)
            """
        )
    )
    rows = conn.execute(
        sa.text(
            """
            SELECT id, owner_user_id, title, created_at
            FROM creation_skills
            WHERE category = 'character'
            ORDER BY owner_user_id, title, created_at DESC, id DESC
            """
        )
    ).fetchall()
    groups: dict[tuple[str, str], list] = defaultdict(list)
    titles_by_owner: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        groups[(row.owner_user_id, row.title)].append(row)
        titles_by_owner[row.owner_user_id].add(row.title)

    updates: list[tuple[str, str]] = []
    for (owner, title), members in groups.items():
        if len(members) <= 1:
            continue
        used = titles_by_owner[owner]
        n = 2
        for row in members[1:]:
            while True:
                suffix = f" ({n})"
                base_budget = _TITLE_MAX - len(suffix)
                candidate = (
                    f"{title}{suffix}"
                    if len(title) + len(suffix) <= _TITLE_MAX
                    else f"{title[:base_budget]}{suffix}"
                )
                n += 1
                if candidate not in used:
                    used.add(candidate)
                    updates.append((row.id, candidate))
                    break

    for skill_id, new_title in updates:
        conn.execute(
            sa.text("UPDATE creation_skills SET title = :title WHERE id = :id"),
            {"title": new_title, "id": skill_id},
        )


def upgrade() -> None:
    _rename_duplicate_character_titles()
    op.create_index(
        "uq_creation_skills_owner_character_title",
        "creation_skills",
        ["owner_user_id", "title"],
        unique=True,
        postgresql_where=sa.text("category = 'character'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_creation_skills_owner_character_title",
        table_name="creation_skills",
        postgresql_where=sa.text("category = 'character'"),
    )
