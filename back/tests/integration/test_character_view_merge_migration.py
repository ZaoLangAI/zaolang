"""Focused data-preservation checks for the character-view-merge migration
(`20260816_1000_merge_character_views.py`) — same shape as
`test_runtime_config_migration.py`: the SQL-heavy body only makes sense
against a live database (already exercised by `alembic upgrade head` in CI),
so this covers the pure helper `_as_dict` and the legacy-view mapping table
directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260816_1000_merge_character_views.py"
    )
    spec = importlib.util.spec_from_file_location("character_view_merge_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_view_kinds_map_onto_the_new_characterviewangle_values() -> None:
    migration = _migration()
    assert migration._LEGACY_TO_VIEW == {
        "character_front": "front",
        "character_side": "side",
        "character_back": "back",
    }
    # `front` must be first: it is the priority order `_merge_workflow_
    # templates` picks a survivor kind from when more than one legacy kind
    # has an active row for the same operation.
    assert migration._LEGACY_VIEW_KINDS[0] == "character_front"
    assert set(migration._LEGACY_VIEW_KINDS) == set(migration._LEGACY_TO_VIEW)


def test_as_dict_parses_a_json_string_column() -> None:
    migration = _migration()
    assert migration._as_dict('{"character": {"reference_assets": []}}') == {
        "character": {"reference_assets": []}
    }


def test_as_dict_passes_through_an_already_decoded_mapping() -> None:
    migration = _migration()
    payload = {"character": {"reference_assets": [{"view": "character_front"}]}}
    assert migration._as_dict(payload) == payload


def test_as_dict_tolerates_garbage_input_instead_of_raising() -> None:
    migration = _migration()
    assert migration._as_dict("not json") == {}
    assert migration._as_dict(None) == {}
    assert migration._as_dict(["not", "a", "dict"]) == {}
