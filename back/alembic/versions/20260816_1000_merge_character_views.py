"""merge character front/side/back into one asset_kind + add multi-output column

Three changes, all serving the same product change ("角色的正面、侧面与背面合并为
角色图，由其对应工作流实现提供三个图"):

1. `ImageAssetKind.CHARACTER_FRONT`/`_SIDE`/`_BACK` collapse into one
   `CHARACTER` value (`app.models.enums`) — a job now names which view(s) it
   wants via `GenerationParams.character_views` instead of picking a
   different `asset_kind` per view. Every `generation_workflow_templates`
   row still keyed under one of the three legacy `asset_kind`s is folded
   into a single `character` row per operation, same adopt-or-deactivate
   shape as `20260816_0900_merge_image_workflow_templates`: whichever legacy
   kind has an active row survives (front, if present, wins — that was the
   only one ever exercised in practice), renamed in place; any other
   legacy-kind active row for the same operation is deactivated, not merged,
   since `image_asset_graph`'s shape has never varied by kind.

2. Every character skill's own `reference_assets[].view` tag is renamed the
   same way (`character_front` -> `front`, etc.) so `CharacterViewAngle`'s
   plain `front`/`side`/`back` values are also what already-generated data
   carries, not just what a new job writes going forward.

3. `generation_jobs.output_asset_ids_json` is added — the multi-output list
   a "补全侧面/背面" completion job (`character_views=["side","back"]`)
   populates; `NULL` for everything else, including every existing row.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c1d4e7f0a3b6"
down_revision: str | None = "b4c8e1f6a3d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHARACTER_KIND = "character"
_CHARACTER_CATEGORY = "character"
# Priority order when more than one legacy kind has an active row for the
# same operation: `front` wins, since that was the only one ever
# meaningfully customized in practice (see the module docstring).
_LEGACY_VIEW_KINDS = ("character_front", "character_side", "character_back")
_LEGACY_TO_VIEW = {"character_front": "front", "character_side": "side", "character_back": "back"}


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column("output_asset_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _merge_workflow_templates()
    _rename_character_reference_views()


def _merge_workflow_templates() -> None:
    bind = op.get_bind()
    operations = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT operation FROM generation_workflow_templates "
                "WHERE asset_kind = ANY(:kinds)"
            ).bindparams(kinds=list(_LEGACY_VIEW_KINDS))
        )
    ]

    for operation in operations:
        active_by_kind = {
            row["asset_kind"]: row["id"]
            for row in bind.execute(
                sa.text(
                    "SELECT id, asset_kind FROM generation_workflow_templates "
                    "WHERE operation = :op AND asset_kind = ANY(:kinds) AND is_active = true"
                ).bindparams(op=operation, kinds=list(_LEGACY_VIEW_KINDS))
            )
            .mappings()
            .all()
        }
        if not active_by_kind:
            continue

        survivor_kind = next(k for k in _LEGACY_VIEW_KINDS if k in active_by_kind)
        survivor_id = active_by_kind[survivor_kind]
        already_character = bind.execute(
            sa.text(
                "SELECT id FROM generation_workflow_templates "
                "WHERE operation = :op AND asset_kind = :kind AND is_active = true"
            ).bindparams(op=operation, kind=_CHARACTER_KIND)
        ).first()

        if already_character is None:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates SET asset_kind = :kind WHERE id = :id"
                ).bindparams(kind=_CHARACTER_KIND, id=survivor_id)
            )
        else:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates SET is_active = false WHERE id = :id"
                ).bindparams(id=survivor_id)
            )

        other_ids = [row_id for kind, row_id in active_by_kind.items() if row_id != survivor_id]
        if other_ids:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates SET is_active = false "
                    "WHERE id = ANY(:ids)"
                ).bindparams(ids=other_ids)
            )


def _rename_character_reference_views() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, params_json FROM creation_skills WHERE category = :category"
            ).bindparams(category=_CHARACTER_CATEGORY)
        )
        .mappings()
        .all()
    )
    for row in rows:
        params = _as_dict(row["params_json"])
        character = params.get("character")
        if not isinstance(character, dict):
            continue
        entries = character.get("reference_assets")
        if not isinstance(entries, list):
            continue
        changed = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            view = entry.get("view")
            if view in _LEGACY_TO_VIEW:
                entry["view"] = _LEGACY_TO_VIEW[view]
                changed = True
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE creation_skills SET params_json = CAST(:params_json AS jsonb) "
                "WHERE id = :id"
            ).bindparams(params_json=json.dumps(params), id=row["id"])
        )


def _as_dict(raw: Any) -> dict[str, Any]:
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def downgrade() -> None:
    # Which legacy kind a merged `character` row (or reference-asset view)
    # came from is not recorded anywhere, so there is nothing sound to
    # restore — same reasoning as `20260816_0900_merge_image_workflow_
    # templates`'s downgrade. Only the added column is reversible.
    op.drop_column("generation_jobs", "output_asset_ids_json")
