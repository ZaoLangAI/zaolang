"""`prompt_builder`: every character/scene pass composes deterministically
and the planner can never pull a pass back into the wrong layout."""

from __future__ import annotations

from app.domain.image_assets import prompt_builder as pb
from app.domain.image_assets.vocabulary import EXPRESSION_PRESETS, PERIOD_PRESETS


def test_resolve_pass_picks_each_pass_kind() -> None:
    assert pb.resolve_pass({}, asset_kind="character", character_view="front") is (
        pb.AssetPass.CHARACTER_SHEET
    )
    assert pb.resolve_pass({}, asset_kind="character", character_view="side") is (
        pb.AssetPass.CHARACTER_COMPLETION
    )
    assert (
        pb.resolve_pass(
            {"character_expressions": ["smile"]}, asset_kind="character", character_view="front"
        )
        is pb.AssetPass.CHARACTER_EXPRESSIONS
    )
    assert pb.resolve_pass({}, asset_kind="scene", character_view=None) is pb.AssetPass.SCENE
    assert (
        pb.resolve_pass(
            {"scene_variants": [{"lighting": "day"}, {"lighting": "dusk"}]},
            asset_kind="scene",
            character_view=None,
        )
        is pb.AssetPass.SCENE_VARIANT_GROUP
    )
    assert pb.resolve_pass({}, asset_kind="cover", character_view=None) is pb.AssetPass.OTHER


def test_character_sheet_keeps_identity_and_appends_layout_and_medium() -> None:
    prompt, negative = pb.compose(
        pb.AssetPass.CHARACTER_SHEET, prompt="林夏，短发", negative=None, params={}
    )
    assert prompt.startswith("林夏，短发")
    assert pb.CHARACTER_SHEET_LAYOUT_SUFFIX in prompt
    assert prompt.endswith(pb.CHARACTER_PHOTOREAL_MEDIUM)
    assert negative == pb.CHARACTER_PHOTOREAL_NEGATIVE


def test_outfit_change_with_a_reference_locks_identity_to_reference_one() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.CHARACTER_SHEET,
        prompt="白色婚纱，头纱",
        negative=None,
        params={"character_outfit_label": "婚礼"},
        has_reference=True,
    )
    assert prompt.startswith(pb.OUTFIT_CHANGE_PREFIX.format(label="婚礼"))
    assert pb.CHARACTER_SHEET_LAYOUT_SUFFIX in prompt


def test_expression_grid_is_never_a_sheet() -> None:
    prompt, negative = pb.compose(
        pb.AssetPass.CHARACTER_EXPRESSIONS,
        prompt="林夏，二次元动漫风格",
        negative=None,
        params={"character_expressions": ["smile", "smirk", "breakdown", "shy", "anger"]},
    )
    assert prompt.startswith(pb.EXPRESSION_IDENTITY_PREFIX)
    assert pb.CHARACTER_SHEET_LAYOUT_SUFFIX not in prompt
    assert "共 5 个等大分格" in prompt and "排成 2 行" in prompt
    assert "居中排列" in prompt
    for key in ("smile", "smirk", "breakdown", "shy", "anger"):
        assert EXPRESSION_PRESETS[key].prompt in prompt
    # Anime medium kept, photoreal rejected; per-cell negatives stay out.
    assert pb.CHARACTER_PHOTOREAL_MEDIUM not in prompt
    assert negative is not None and pb.CHARACTER_ANIME_NEGATIVE in negative
    assert "设定图" in negative
    assert EXPRESSION_PRESETS["anger"].negative not in negative


def test_a_single_expression_is_a_close_up_with_its_own_negative() -> None:
    prompt, negative = pb.compose(
        pb.AssetPass.CHARACTER_EXPRESSIONS,
        prompt="林夏",
        negative=None,
        params={"character_expressions": ["restrained"]},
    )
    assert "单人头肩特写" in prompt
    assert negative is not None and EXPRESSION_PRESETS["restrained"].negative in negative


def test_scene_presets_add_fragments_and_era_cues() -> None:
    prompt, negative = pb.compose(
        pb.AssetPass.SCENE,
        prompt="老式客厅",
        negative="人物",
        params={"scene_lighting": "night_interior", "scene_period": "republic"},
    )
    assert prompt.startswith("老式客厅")
    assert "夜晚室内" in prompt
    assert "年代线索" in prompt and PERIOD_PRESETS["republic"].cues[0] in prompt
    assert negative is not None and negative.startswith("人物")
    assert PERIOD_PRESETS["republic"].pitfalls[0] in negative
    assert not prompt.startswith("以参考图1为基准")


def test_scene_variant_from_a_master_plate_pins_the_geometry() -> None:
    prompt, _ = pb.compose(
        pb.AssetPass.SCENE,
        prompt="老式客厅",
        negative=None,
        params={"scene_state": "damage_medium", "scene_weather": "rain"},
        has_reference=True,
    )
    assert prompt.startswith(pb.SCENE_VARIANT_PREFIX.format(label="雨 / 战损·中"))


def test_a_scene_without_presets_is_left_alone() -> None:
    assert pb.compose(pb.AssetPass.SCENE, prompt="便利店", negative=None, params={}) == (
        "便利店",
        None,
    )


def test_scene_variant_group_lists_one_line_per_image() -> None:
    params = {"scene_variants": [{"lighting": "day"}, {"lighting": "dusk", "weather": "rain"}]}
    prompt, negative = pb.compose(
        pb.AssetPass.SCENE_VARIANT_GROUP, prompt="老式客厅", negative=None, params=params
    )
    assert "共 2 张独立的场景图" in prompt
    assert "图1：" in prompt and "图2：" in prompt
    assert negative is not None and "分格" in negative
    assert pb.group_labels(params) == ["白天", "黄昏 / 雨"]


def test_sanitize_enhancements_drops_sheet_layout_and_foreign_eras() -> None:
    kept = pb.sanitize_enhancements(
        pb.AssetPass.CHARACTER_EXPRESSIONS,
        ["补上左侧全身三视图与色板", "五官保持一致", ""],
        params={},
    )
    assert kept == ["五官保持一致"]
    kept = pb.sanitize_enhancements(
        pb.AssetPass.SCENE,
        ["加入八十年代的挂历", "民国花砖地面", "柔和的环境光"],
        params={"scene_period": "republic"},
    )
    assert kept == ["民国花砖地面", "柔和的环境光"]
    # A character sheet keeps its own layout additions.
    assert pb.sanitize_enhancements(pb.AssetPass.CHARACTER_SHEET, ["三视图"], params={}) == [
        "三视图"
    ]
