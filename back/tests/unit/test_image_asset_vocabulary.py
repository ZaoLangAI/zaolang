"""The character/scene preset vocabularies stay complete and phraseable."""

from __future__ import annotations

import pytest

from app.domain.image_assets import vocabulary as vocab


@pytest.mark.parametrize(
    ("keys", "table"),
    [
        (vocab.CHARACTER_EXPRESSIONS, vocab.EXPRESSION_PRESETS),
        (vocab.SCENE_LIGHTINGS, vocab.LIGHTING_PRESETS),
        (vocab.SCENE_WEATHERS, vocab.WEATHER_PRESETS),
        (vocab.SCENE_STATES, vocab.STATE_PRESETS),
        (vocab.SCENE_PERIODS, vocab.PERIOD_PRESETS),
    ],
)
def test_every_literal_value_has_a_complete_preset(keys, table) -> None:
    assert set(keys) == set(table)
    for key in keys:
        preset = table[key]
        assert preset.label.strip(), key
        assert len(preset.label) <= vocab.MAX_PRESET_LABEL_LEN, key
        assert preset.prompt.strip(), key
        assert preset.negative.strip(), key


def test_period_presets_carry_era_cues_and_pitfalls() -> None:
    for key, preset in vocab.PERIOD_PRESETS.items():
        assert preset.cues, key
        assert preset.pitfalls, key


def test_expression_grid_covers_every_supported_count() -> None:
    for count in range(1, vocab.MAX_CHARACTER_EXPRESSIONS + 1):
        rows, cols = vocab.expression_grid(count)
        assert rows * cols >= count
    assert vocab.expression_grid(1) == (1, 1)
    assert vocab.expression_grid(6) == (2, 3)
    assert vocab.expression_grid(99) == (3, 3)


def test_scene_presets_from_reads_both_param_spellings() -> None:
    assert vocab.scene_presets_from({"scene_lighting": "dusk", "scene_state": "bogus"}) == {
        "lighting": "dusk"
    }
    assert vocab.scene_presets_from({"weather": "rain", "period": "republic"}) == {
        "weather": "rain",
        "period": "republic",
    }


def test_scene_preset_label_reads_lighting_first() -> None:
    label = vocab.scene_preset_label(
        {
            "period": "republic",
            "state": "damage_medium",
            "lighting": "night_interior",
            "weather": "rain",
        }
    )
    assert label == "夜·室内 / 雨 / 战损·中 / 民国"
