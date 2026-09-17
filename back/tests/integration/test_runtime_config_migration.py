"""Focused data-preservation checks for the runtime-config migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


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


def test_a_legacy_binding_resolves_to_the_primary_endpoint_serving_its_model() -> None:
    """`_migrate_agent_bindings` itself is no longer exercisable here: it writes
    `agent_profiles.model`, a column a later revision drops, and the test schema
    is built from today's metadata. Its endpoint-resolution half is a pure
    function, and that is the part that still maps onto how agents bind now.
    """
    migration = _migration()
    endpoints = {
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
        "disabled": {
            "kind": "general",
            "enabled": False,
            "models": ["safe-model"],
            "role": "primary",
        },
    }

    assert migration._compatible_endpoint(endpoints, "safe-model") == "primary"
    assert migration._compatible_endpoint(endpoints, "unknown-model") is None
    assert migration._compatible_endpoint(endpoints, None) is None


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
