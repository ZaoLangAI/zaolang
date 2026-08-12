"""Focused data-preservation checks for the runtime-config migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260811_1200_refactor_runtime_config.py"
    )
    spec = importlib.util.spec_from_file_location("runtime_config_refactor_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_agent_binding_moves_to_the_role_default_profile(db: Session) -> None:
    migration = _migration()
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)

    migration._migrate_agent_bindings(
        db.connection(),
        {
            "bindings": {
                "safety": {
                    "model": "safe-model",
                    "max_tokens": 2048,
                    "temperature": 0.15,
                    "reasoning_model": True,
                }
            }
        },
        {
            "endpoints": {
                "backup": {
                    "kind": "general",
                    "enabled": True,
                    "models": ["safe-model"],
                    "role": "backup",
                    "backup_order": 10,
                },
                "primary": {
                    "kind": "general",
                    "enabled": True,
                    "models": ["safe-model"],
                    "role": "primary",
                },
            }
        },
    )
    db.expire_all()

    profile = agent_skills_service.default_profile(db, "safety")
    assert profile is not None
    assert profile.model == "safe-model"
    assert profile.default_endpoint_id == "primary"
    assert profile.max_tokens == 2048
    assert profile.temperature_milli == 150
    assert profile.reasoning_model is True


def test_migration_normalizes_words_and_removes_illegal_flags() -> None:
    migration = _migration()
    assert migration._normalise_words(["  禁止词 ", "禁止词", "CASE", "case", ""]) == [
        "禁止词",
        "case",
    ]
    assert migration._clean_feature_flags(
        {
            "video_generation": False,
            "public_registration": True,
            "shortform_studio": False,
            "semantic_search": True,
            "rollout_percentages": {
                "video_generation": 120,
                "shortform_studio": -2,
                "public_registration": 50,
            },
        }
    ) == {
        "video_generation": False,
        "public_registration": True,
        "shortform_studio": False,
        "rollout_percentages": {"video_generation": 100, "shortform_studio": 0},
    }
