"""P2-8 migration B: the downgrade rebuilds the dropped mirror from the
tables in `project()`'s shape and order. The function is pure; CI runs
`alembic upgrade head` live."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
from types import ModuleType


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261003_1200_drop_reference_assets_mirror.py"
    )
    spec = importlib.util.spec_from_file_location("drop_reference_assets_mirror", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def _entry(variant: str, asset: str, entry_type: str, **kw) -> dict:
    return {
        "variant_id": variant,
        "asset_id": asset,
        "entry_type": entry_type,
        "view": kw.get("view"),
        "label": kw.get("label"),
        "status": kw.get("status", "approved"),
        "is_anchor": kw.get("is_anchor", False),
        "sort_order": kw.get("sort_order", 0),
        "created_at": kw.get("created_at", T0),
    }


def test_the_rebuilt_mirror_matches_the_projection() -> None:
    variants = [
        {"id": "v_wed", "name": "婚礼", "is_default": False, "sort_order": 1, "created_at": T0},
        {"id": "v_def", "name": "默认造型", "is_default": True, "sort_order": 0, "created_at": T0},
    ]
    entries = [
        _entry("v_wed", "a_wed", "character_sheet", view="front"),
        _entry("v_def", "a_side", "view", view="side", sort_order=1),
        _entry("v_def", "a_sheet", "character_sheet", view="front", is_anchor=True),
        _entry("v_def", "a_cand", "character_sheet", view="front", status="candidate"),
        _entry("v_def", "a_face", "expression_sheet", label="表情·微笑", sort_order=2),
    ]
    rebuilt = _migration().project_rows("character", variants, entries)
    assert [(r["asset_id"], r["view"], r["label"]) for r in rebuilt] == [
        ("a_sheet", "front", None),
        ("a_side", "side", None),
        ("a_face", "general", "表情·微笑"),
        ("a_wed", "front", "婚礼"),
    ]
    assert rebuilt[0]["created_at"] == T0.isoformat()


def test_scene_views_map_like_p0() -> None:
    variants = [
        {"id": "v", "name": "主场景", "is_default": True, "sort_order": 0, "created_at": T0}
    ]
    entries = [_entry("v", "m", "master"), _entry("v", "d", "shot", view="detail", sort_order=1)]
    rebuilt = _migration().project_rows("scene_asset", variants, entries)
    assert [(r["asset_id"], r["view"]) for r in rebuilt] == [("m", "establishing"), ("d", "detail")]
