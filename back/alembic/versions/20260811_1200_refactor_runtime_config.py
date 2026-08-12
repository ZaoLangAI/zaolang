"""refactor runtime config ownership and agent model bindings

Revision ID: 8a61d47c2f10
Revises: 5b2c8e14a7f3
Create Date: 2026-08-11 12:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "8a61d47c2f10"
down_revision: str | None = "5b2c8e14a7f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_MODERATION_KEYS = (
    "content_moderation",
    "learning_moderation",
    "skill_moderation",
)
_REMOVED_KEYS = ("providers", "agents", "moderation", "llm_reliability")
_KEPT_FLAGS = ("video_generation", "public_registration", "shortform_studio")
_ROLLOUT_FLAGS = ("video_generation", "shortform_studio")


def upgrade() -> None:
    op.add_column("agent_profiles", sa.Column("model", sa.String(length=160), nullable=True))
    bind = op.get_bind()
    active = _active_values(bind)

    legacy_words = _normalise_words((active.get("moderation") or {}).get("blocked_keywords", []))
    for key in _NEW_MODERATION_KEYS:
        current_words = _normalise_words((active.get(key) or {}).get("blocked_keywords", []))
        _write_version(
            bind,
            key,
            {"blocked_keywords": _normalise_words(current_words + legacy_words)},
        )

    _write_version(bind, "feature_flags", _clean_feature_flags(active.get("feature_flags") or {}))

    _migrate_agent_bindings(bind, active.get("agents") or {}, active.get("llm_providers") or {})
    bind.execute(
        sa.text("UPDATE platform_configs SET is_active = false WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(_REMOVED_KEYS)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE platform_configs SET is_active = false WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(_NEW_MODERATION_KEYS)},
    )
    for key in _REMOVED_KEYS:
        bind.execute(
            sa.text(
                "UPDATE platform_configs SET is_active = true "
                "WHERE key = :key AND version = "
                "(SELECT max(version) FROM platform_configs WHERE key = :key)"
            ),
            {"key": key},
        )
    op.drop_column("agent_profiles", "model")


def _active_values(bind: sa.Connection) -> dict[str, dict[str, Any]]:
    rows = bind.execute(
        sa.text("SELECT key, value_json FROM platform_configs WHERE is_active = true")
    ).all()
    return {str(key): _as_dict(value) for key, value in rows}


def _write_version(bind: sa.Connection, key: str, value: dict[str, Any]) -> None:
    latest = bind.execute(
        sa.text("SELECT coalesce(max(version), 0) FROM platform_configs WHERE key = :key"),
        {"key": key},
    ).scalar_one()
    version = int(latest) + 1
    bind.execute(
        sa.text("UPDATE platform_configs SET is_active = false WHERE key = :key"), {"key": key}
    )
    bind.execute(
        sa.text(
            "INSERT INTO platform_configs "
            "(id, key, version, value_json, is_active, note, created_by_user_id, created_at) "
            "VALUES (:id, :key, :version, CAST(:value AS jsonb), true, :note, NULL, now())"
        ),
        {
            "id": f"cfg_refactor_{key}_{version}"[:40],
            "key": key,
            "version": version,
            "value": json.dumps(value, ensure_ascii=False),
            "note": "运行时配置中心归属迁移",
        },
    )


def _migrate_agent_bindings(
    bind: sa.Connection, agents: dict[str, Any], providers: dict[str, Any]
) -> None:
    bindings = agents.get("bindings") or {}
    endpoints = providers.get("endpoints") or {}
    for role, raw in bindings.items():
        if not isinstance(raw, dict):
            continue
        model = str(raw.get("model") or "").strip() or None
        endpoint_id = _compatible_endpoint(endpoints, model)
        temperature = raw.get("temperature")
        temperature_milli = round(float(temperature) * 1000) if temperature is not None else None
        bind.execute(
            sa.text(
                "UPDATE agent_profiles SET model = :model, "
                "default_endpoint_id = coalesce(default_endpoint_id, :endpoint_id), "
                "max_tokens = coalesce(max_tokens, :max_tokens), "
                "temperature_milli = coalesce(temperature_milli, :temperature_milli), "
                "reasoning_model = coalesce(reasoning_model, :reasoning_model) "
                "WHERE role = :role AND is_default = true"
            ),
            {
                "role": role,
                "model": model,
                "endpoint_id": endpoint_id,
                "max_tokens": raw.get("max_tokens"),
                "temperature_milli": temperature_milli,
                "reasoning_model": raw.get("reasoning_model"),
            },
        )


def _compatible_endpoint(endpoints: dict[str, Any], model: str | None) -> str | None:
    if not model:
        return None
    matches: list[tuple[tuple[int, int, str], str]] = []
    for endpoint_id, raw in endpoints.items():
        if not isinstance(raw, dict):
            continue
        if not raw.get("enabled", True) or raw.get("kind", "general") != "general":
            continue
        if model not in (raw.get("models") or []):
            continue
        role_rank = 0 if raw.get("role") == "primary" else 1
        matches.append(((role_rank, int(raw.get("backup_order") or 100), endpoint_id), endpoint_id))
    matches.sort()
    return matches[0][1] if matches else None


def _clean_feature_flags(flags: dict[str, Any]) -> dict[str, Any]:
    cleaned = {name: bool(flags.get(name, True)) for name in _KEPT_FLAGS}
    rollout = flags.get("rollout_percentages") or {}
    cleaned["rollout_percentages"] = {
        name: max(0, min(100, int(rollout[name]))) for name in _ROLLOUT_FLAGS if name in rollout
    }
    return cleaned


def _normalise_words(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        word = str(value).strip().casefold()
        if word and word not in seen:
            seen.add(word)
            result.append(word)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}
