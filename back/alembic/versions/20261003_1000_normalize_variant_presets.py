"""normalize look / scene variant presets (P2-6)

`VariantPresets.age_stage` was a free string; it is now the `AgeStage`
vocabulary (`app.domain.image_assets.vocabulary`), and the service rejects
the other kind's keys. This rewrites existing rows to match:

- a look keeps only `age_stage`, mapped from a token or a Chinese label
  (童年/少年/青年/壮年/中年/老年 and close synonyms); anything unrecognised
  is dropped and counted in the log;
- a scene variant keeps only lighting / weather / state / period.

The downgrade is a no-op: the dropped free-text values are not restorable,
and the normalised rows remain valid for the previous code.

Revision ID: d1a8a7ac68fd
Revises: d3626982aba7
Create Date: 2026-10-03 10:00:00+00:00
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "d1a8a7ac68fd"
down_revision: str | None = "d3626982aba7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

AGE_STAGES = ("child", "teen", "youth", "adult", "middle_aged", "elderly")
AGE_STAGE_ALIASES: dict[str, str] = {
    **{stage: stage for stage in AGE_STAGES},
    "童年": "child",
    "儿童": "child",
    "孩童": "child",
    "幼年": "child",
    "少年": "teen",
    "青少年": "teen",
    "少女": "teen",
    "青年": "youth",
    "壮年": "adult",
    "成年": "adult",
    "中年": "middle_aged",
    "老年": "elderly",
    "晚年": "elderly",
}
SCENE_KEYS = ("lighting", "weather", "state", "period")


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def normalize_presets(kind: str, raw: Any) -> tuple[dict[str, Any], bool]:
    """`(normalised presets, dropped an unrecognised age stage)`."""
    presets = _as_dict(raw)
    if kind == "look":
        value = presets.get("age_stage")
        if not value:
            return {}, False
        stage = AGE_STAGE_ALIASES.get(str(value).strip())
        return ({"age_stage": stage}, False) if stage else ({}, True)
    return {key: presets[key] for key in SCENE_KEYS if presets.get(key)}, False


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, kind, presets_json FROM skill_asset_variants")).all()
    changed = dropped = 0
    for row in rows:
        normalised, lost = normalize_presets(row.kind, row.presets_json)
        dropped += int(lost)
        if normalised != _as_dict(row.presets_json):
            bind.execute(
                sa.text(
                    "UPDATE skill_asset_variants SET presets_json = CAST(:presets AS JSONB) "
                    "WHERE id = :id"
                ),
                {"presets": json.dumps(normalised, ensure_ascii=False), "id": row.id},
            )
            changed += 1
    logger.info(
        "normalized presets on %s of %s variants; dropped %s unrecognised age stages",
        changed,
        len(rows),
        dropped,
    )


def downgrade() -> None:
    pass
