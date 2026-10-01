"""character looks / scene variants as tables

Moves every character/scene `CreationSkill`'s
`params_json[character|scene]["reference_assets"]` into
`skill_asset_variants` + `skill_asset_entries` (see
`docs/asset-variants-p1.md`). The JSON list is *kept* — from now on it is a
write-through mirror of the tables (`app.domain.asset_variants.service
.sync_mirror`), so this downgrade loses nothing; a later migration drops it.

Mapping (P0 used an entry's `label` as its outfit/variant name):

- every card gets a default variant: 「默认造型」 (character) / 「主场景」 (scene)
- character `front` → `character_sheet`, `side`/`back` → `view`, else `other`;
  a `表情·…` label stays in the default look as an `expression_sheet`, any
  other label becomes (or joins) a look of that name
- scene `establishing` → `master`; `detail`/`reverse` → `shot` keeping the
  view; else `shot`; a label becomes (or joins) a variant of that name
- anchor: the character's first `character_sheet`; the scene's master plate
  (first `establishing`, else first unlabelled — P0's `master_entry`), which
  is retyped `master`
- entries whose asset no longer exists are dropped (counted in the log)

Revision ID: d3626982aba7
Revises: 4b5dd8d301c2
Create Date: 2026-10-01 13:17:11.561670+00:00
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3626982aba7"
down_revision: str | None = "4b5dd8d301c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

DEFAULT_LOOK_NAME = "默认造型"
DEFAULT_SCENE_VARIANT_NAME = "主场景"
_EXPRESSION_LABEL_PREFIX = "表情"
_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def upgrade() -> None:
    op.create_table(
        "skill_asset_variants",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("skill_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "presets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('look', 'scene_variant')", name=op.f("ck_skill_asset_variants_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["creation_skills.id"],
            name=op.f("fk_skill_asset_variants_skill_id_creation_skills"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_asset_variants")),
        sa.UniqueConstraint("id", "skill_id", name="uq_skill_asset_variants_id_skill_id"),
        sa.UniqueConstraint("skill_id", "name", name="uq_skill_asset_variants_skill_id_name"),
    )
    op.create_index(
        "ix_skill_asset_variants_skill_id", "skill_asset_variants", ["skill_id"], unique=False
    )
    op.create_index(
        "uq_skill_asset_variants_default",
        "skill_asset_variants",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "skill_asset_entries",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("variant_id", sa.String(length=40), nullable=False),
        sa.Column("skill_id", sa.String(length=40), nullable=False),
        sa.Column("asset_id", sa.String(length=40), nullable=False),
        sa.Column("entry_type", sa.String(length=24), nullable=False),
        sa.Column("view", sa.String(length=16), nullable=True),
        sa.Column("expressions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("label", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="approved", nullable=False),
        sa.Column("is_anchor", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source_job_id", sa.String(length=40), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('identity_portrait', 'character_sheet', 'view', 'expression_sheet', "
            "'pose', 'outfit_detail', 'prop', 'master', 'shot', 'other')",
            name=op.f("ck_skill_asset_entries_entry_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved')", name=op.f("ck_skill_asset_entries_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_skill_asset_entries_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            name="fk_skill_asset_entries_variant_id_skill_asset_variants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_asset_entries")),
        sa.UniqueConstraint(
            "variant_id", "asset_id", name="uq_skill_asset_entries_variant_id_asset_id"
        ),
    )
    op.create_index(
        "ix_skill_asset_entries_asset_id", "skill_asset_entries", ["asset_id"], unique=False
    )
    op.create_index(
        "ix_skill_asset_entries_skill",
        "skill_asset_entries",
        ["skill_id", "variant_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_skill_asset_entries_anchor",
        "skill_asset_entries",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("is_anchor"),
    )
    _backfill(op.get_bind())


def downgrade() -> None:
    # The JSON mirror still holds every entry, so dropping the tables loses
    # nothing a pre-P1 reader can see.
    op.drop_index(
        "uq_skill_asset_entries_anchor",
        table_name="skill_asset_entries",
        postgresql_where=sa.text("is_anchor"),
    )
    op.drop_index("ix_skill_asset_entries_skill", table_name="skill_asset_entries")
    op.drop_index("ix_skill_asset_entries_asset_id", table_name="skill_asset_entries")
    op.drop_table("skill_asset_entries")
    op.drop_index(
        "uq_skill_asset_variants_default",
        table_name="skill_asset_variants",
        postgresql_where=sa.text("is_default"),
    )
    op.drop_index("ix_skill_asset_variants_skill_id", table_name="skill_asset_variants")
    op.drop_table("skill_asset_variants")


# ---- backfill ---------------------------------------------------------------


def _new_id(prefix: str) -> str:
    """Same shape as `app.models.base.new_id` (kept local: a migration must
    not drift with application code)."""
    now_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    return f"{prefix}_{_encode(now_ms, 10)}{_encode(secrets.randbits(80), 16)}"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _as_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _clean_label(raw: object) -> str | None:
    return raw.strip() or None if isinstance(raw, str) else None


def plan_entries(category: str, refs: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Pure mapping of one card's `reference_assets` onto variants + entries.

    Returns `(variant names in creation order — the first is the default,
    entries)`; each entry carries `variant`, `asset_id`, `entry_type`,
    `view`, `label`, `is_anchor`, `created_at`. Duplicate assets within one
    variant keep the first occurrence.
    """
    is_character = category == "character"
    default = DEFAULT_LOOK_NAME if is_character else DEFAULT_SCENE_VARIANT_NAME
    names = [default]
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    raw = [r for r in refs if isinstance(r, dict) and r.get("asset_id")]

    master_index: int | None = None
    if not is_character:
        for index, ref in enumerate(raw):
            if ref.get("view") == "establishing":
                master_index = index
                break
        if master_index is None:
            master_index = next(
                (i for i, r in enumerate(raw) if _clean_label(r.get("label")) is None), None
            )

    for index, ref in enumerate(raw):
        view = ref.get("view") if isinstance(ref.get("view"), str) else None
        label = _clean_label(ref.get("label"))
        variant = default
        entry_label: str | None = None
        if is_character:
            if label and label.startswith(_EXPRESSION_LABEL_PREFIX):
                entry_type, entry_view, entry_label = "expression_sheet", None, label[:60]
            else:
                if label:
                    variant = label[:40]
                if view == "front":
                    entry_type, entry_view = "character_sheet", "front"
                elif view in ("side", "back"):
                    entry_type, entry_view = "view", view
                else:
                    entry_type, entry_view = "other", None
        else:
            if label:
                variant = label[:40]
            if index == master_index:
                entry_type, entry_view = "master", None
            elif view in ("detail", "reverse"):
                entry_type, entry_view = "shot", view
            else:
                entry_type, entry_view = "shot", None
        if variant not in names:
            names.append(variant)
        key = (variant, str(ref["asset_id"]))
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "variant": variant,
                "asset_id": str(ref["asset_id"]),
                "entry_type": entry_type,
                "view": entry_view,
                "label": entry_label,
                "is_anchor": False,
                "created_at": ref.get("created_at"),
            }
        )

    anchor_type = "character_sheet" if is_character else "master"
    anchor = next((e for e in entries if e["entry_type"] == anchor_type), None)
    if anchor is not None:
        anchor["is_anchor"] = True
    return names, entries


def _parse_ts(raw: object, fallback: dt.datetime) -> dt.datetime:
    if isinstance(raw, str):
        try:
            parsed = dt.datetime.fromisoformat(raw)
        except ValueError:
            return fallback
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return fallback


def _backfill(bind: sa.engine.Connection) -> None:
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, category, params_json, created_at FROM creation_skills "
                "WHERE category IN ('character', 'scene_asset')"
            )
        )
        .mappings()
        .all()
    )
    existing_assets = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT id FROM assets WHERE id IN (SELECT DISTINCT jsonb_array_elements("
                "COALESCE(params_json->'character'->'reference_assets', "
                "params_json->'scene'->'reference_assets', '[]'::jsonb))->>'asset_id' "
                "FROM creation_skills WHERE category IN ('character', 'scene_asset'))"
            )
        )
    }
    dropped = 0
    for row in rows:
        category = row["category"]
        nest = "character" if category == "character" else "scene"
        refs = _as_dict(_as_dict(row["params_json"]).get(nest)).get("reference_assets")
        refs = refs if isinstance(refs, list) else []
        # Dropped *before* planning so the anchor/master is picked among
        # entries that actually survive.
        live = [r for r in refs if isinstance(r, dict) and r.get("asset_id") in existing_assets]
        dropped += sum(1 for r in refs if isinstance(r, dict) and r.get("asset_id")) - len(live)
        names, entries = plan_entries(category, live)
        kind = "look" if category == "character" else "scene_variant"
        variant_ids: dict[str, str] = {}
        for order, name in enumerate(names):
            variant_ids[name] = _new_id("skv")
            bind.execute(
                sa.text(
                    "INSERT INTO skill_asset_variants "
                    "(id, skill_id, kind, name, is_default, sort_order) "
                    "VALUES (:id, :skill_id, :kind, :name, :is_default, :sort_order)"
                ),
                {
                    "id": variant_ids[name],
                    "skill_id": row["id"],
                    "kind": kind,
                    "name": name,
                    "is_default": order == 0,
                    "sort_order": order,
                },
            )
        for order, entry in enumerate(entries):
            bind.execute(
                sa.text(
                    "INSERT INTO skill_asset_entries "
                    "(id, variant_id, skill_id, asset_id, entry_type, view, label, status, "
                    "is_anchor, sort_order, created_at) VALUES (:id, :variant_id, :skill_id, "
                    ":asset_id, :entry_type, :view, :label, 'approved', :is_anchor, "
                    ":sort_order, :created_at)"
                ),
                {
                    "id": _new_id("ske"),
                    "variant_id": variant_ids[entry["variant"]],
                    "skill_id": row["id"],
                    "asset_id": entry["asset_id"],
                    "entry_type": entry["entry_type"],
                    "view": entry["view"],
                    "label": entry["label"],
                    "is_anchor": entry["is_anchor"],
                    "sort_order": order,
                    "created_at": _parse_ts(entry["created_at"], row["created_at"]),
                },
            )
    logger.info(
        "skill asset variants backfill: %d cards, %d entries dropped (missing asset)",
        len(rows),
        dropped,
    )
