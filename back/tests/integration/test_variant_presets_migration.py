"""P2-6 migration: look / scene variant presets normalised to the
vocabulary. The function is pure; `alembic upgrade head` in CI runs it live."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261003_1000_normalize_variant_presets.py"
    )
    spec = importlib.util.spec_from_file_location("normalize_variant_presets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("raw", "expected", "dropped"),
    [
        ({"age_stage": "青年"}, {"age_stage": "youth"}, False),
        ({"age_stage": " 少年 "}, {"age_stage": "teen"}, False),
        ({"age_stage": "middle_aged"}, {"age_stage": "middle_aged"}, False),
        ({"age_stage": "大学时期"}, {}, True),
        ({"age_stage": "老年", "lighting": "dusk"}, {"age_stage": "elderly"}, False),
        ({}, {}, False),
        ('{"age_stage": "中年"}', {"age_stage": "middle_aged"}, False),
    ],
)
def test_a_look_keeps_only_a_known_age_stage(raw, expected, dropped) -> None:
    assert _migration().normalize_presets("look", raw) == (expected, dropped)


def test_a_scene_variant_keeps_only_scene_axes() -> None:
    normalised, dropped = _migration().normalize_presets(
        "scene_variant", {"lighting": "dusk", "weather": None, "age_stage": "青年", "x": 1}
    )
    assert (normalised, dropped) == ({"lighting": "dusk"}, False)
