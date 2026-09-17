"""The deterministic script lint (`app.domain.script_writing.lint`)."""

from __future__ import annotations

from typing import Any

from app.agents import copywriter
from app.domain.script_writing import lint
from app.domain.skill_library import service as skill_library
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS


def _script(*scenes: dict[str, Any], characters: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": "测试",
        "characters": [{"name": name, "traits": ""} for name in characters or []],
        "scenes": list(scenes),
    }


def _scene(heading: str, *blocks: tuple[str, str] | tuple[str, str, str]) -> dict[str, Any]:
    return {
        "heading": heading,
        "blocks": [
            {"type": item[0], "text": item[1], "character": item[2] if len(item) > 2 else None}
            for item in blocks
        ],
    }


def _codes(issues: list[lint.LintIssue]) -> list[str]:
    return [issue.code for issue in issues]


def test_a_clean_script_has_no_findings() -> None:
    script = _script(
        _scene(
            "夜·便利店",
            ("scene", "凌晨的便利店，左侧冷白灯管照亮货架，玻璃门外下着雨"),
            ("camera", "中景，缓慢向左平移"),
            ("action", "林夏把找零推过柜台，手指停在硬币上"),
            ("dialogue", "你还要别的吗？", "林夏"),
            ("breakpoint", "建议在此处切分"),
            ("camera", "近景，固定机位"),
            ("dialogue", "不用了。", "陈默"),
        ),
        characters=["林夏", "陈默"],
    )
    assert lint.lint_script(script) == []


def test_block_rules_flag_vague_words_emotion_labels_people_and_camera_gaps() -> None:
    script = _script(
        _scene(
            "日·天台",
            ("scene", "林夏站在天台边，电影感的逆光"),
            ("action", "他很紧张地看着远处"),
            ("camera", "镜头缓缓移动"),
        ),
        characters=["林夏"],
    )
    issues = lint.lint_script(script)
    codes = _codes(issues)
    assert "vague_words" in codes
    assert "emotion_label" in codes
    assert "person_in_scene_block" in codes
    assert "camera_missing_shot_size" in codes
    assert "camera_directionless_move" in codes
    person = next(issue for issue in issues if issue.code == "person_in_scene_block")
    assert (person.scene_index, person.block_index, person.dimension) == (0, 0, "subject")


def test_three_same_shot_sizes_in_a_row_are_flagged_once() -> None:
    script = _script(
        _scene(
            "日·客厅",
            ("camera", "中景，固定机位"),
            ("action", "他坐下"),
            ("camera", "中景，缓慢推进"),
            ("camera", "中景，向右摇"),
            ("camera", "中景，跟拍"),
        )
    )
    runs = [issue for issue in lint.lint_script(script) if issue.code == "same_shot_run"]
    assert len(runs) == 1
    assert runs[0].block_index == 3


def test_longest_shot_size_wins() -> None:
    assert lint.shot_size("大远景，缓慢升起") == "大远景"
    assert lint.shot_size("中近景，固定") == "中近景"
    assert lint.shot_size("大特写，推进") == "大特写"
    assert lint.shot_size("缓慢推进") is None


def test_an_overlong_segment_is_flagged_with_the_frontend_breakpoint_key() -> None:
    long_line = "我" * int((MAX_GENERATION_DURATION_SECONDS + 5) * lint.DIALOGUE_CHARS_PER_SECOND)
    script = _script(
        _scene(
            "夜·车里",
            ("camera", "近景，固定机位"),
            ("dialogue", "短句。", "甲方"),
            ("breakpoint", "切"),
            ("dialogue", long_line, "乙方"),
        )
    )
    too_long = [issue for issue in lint.lint_script(script) if issue.code == "segment_too_long"]
    assert len(too_long) == 1
    # The unclosed tail after the first breakpoint is `{heading}#1`, exactly as
    # `script-breakpoint.ts::trailingBreakpoint` keys it.
    assert too_long[0].breakpoint_key == "夜·车里#1"
    assert too_long[0].block_index is None


def test_vertical_dialogue_in_a_wide_shot_is_flagged_only_when_vertical() -> None:
    script = _script(
        _scene("日·操场", ("camera", "远景，固定机位"), ("dialogue", "你来了。", "甲方"))
    )
    assert "vertical_wide_shot_with_dialogue" in _codes(lint.lint_script(script, vertical=True))
    assert "vertical_wide_shot_with_dialogue" not in _codes(
        lint.lint_script(script, vertical=False)
    )


def test_more_than_three_speakers_is_an_episode_level_note() -> None:
    script = _script(
        _scene(
            "日·会议室",
            ("dialogue", "一", "甲"),
            ("dialogue", "二", "乙"),
            ("dialogue", "三", "丙"),
            ("dialogue", "四", "丁"),
        )
    )
    issue = next(issue for issue in lint.lint_script(script) if issue.code == "too_many_speakers")
    assert issue.scene_index is None


def test_vertical_delivery_defaults_to_vertical() -> None:
    assert lint.is_vertical_delivery(None) is True
    assert lint.is_vertical_delivery(["manual_download"]) is True
    assert lint.is_vertical_delivery(["douyin"]) is True
    assert lint.is_vertical_delivery(["youtube"]) is False


def test_lint_vocabulary_matches_the_coach_prompts() -> None:
    """Every word the lint checks is one the script coach already tells the
    model to avoid or use — if a prompt rule is reworded, this fails."""
    enhance = copywriter._ENHANCE_CONTRACT
    rules = copywriter._BLOCK_TYPE_RULES
    for word in lint.VAGUE_WORDS:
        assert word in enhance, word
    for word in lint.EMOTION_LABELS:
        assert word in rules, word
    for size in lint.SHOT_SIZES:
        assert size in rules, size
    assert lint.DIRECTIONLESS_MOVE_EXAMPLE in rules


def test_every_lint_dimension_maps_to_format_skills() -> None:
    dimensions = {
        issue_dimension
        for issue_dimension in ("subject", "camera", "action", "pacing")
        if skill_library.format_skill_titles(issue_dimension)
    }
    assert dimensions == {"subject", "camera", "action", "pacing"}
