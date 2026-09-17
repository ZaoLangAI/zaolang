"""The backend port of the frontend's breakpoint ordering must produce the
exact same keys as `front/src/features/script/script-breakpoint.ts`."""

from __future__ import annotations

from typing import Any

from app.domain.script_writing import breakpoints


def _scene(heading: str, *types: str) -> dict[str, Any]:
    return {
        "heading": heading,
        "blocks": [{"type": kind, "text": f"{kind} 文字", "character": None} for kind in types],
    }


def test_breakpoints_are_keyed_by_scene_heading_and_ordinal() -> None:
    script = {
        "scenes": [
            _scene("日·客厅", "scene", "action", "breakpoint", "dialogue", "breakpoint"),
            _scene("夜·街道", "camera", "breakpoint"),
        ]
    }
    assert breakpoints.ordered_breakpoint_keys(script) == ["日·客厅#0", "日·客厅#1", "夜·街道#0"]


def test_an_unclosed_shootable_tail_gets_a_trailing_closer() -> None:
    script = {"scenes": [_scene("日·天台", "scene", "breakpoint", "action", "dialogue")]}
    segments = breakpoints.ordered_segments(script)
    assert [segment.key for segment in segments] == ["日·天台#0", "日·天台#1"]
    closer = segments[-1]
    assert (closer.start, closer.end) == (2, 4)


def test_a_scene_ending_on_a_breakpoint_has_no_closer() -> None:
    script = {"scenes": [_scene("日·车内", "action", "breakpoint")]}
    assert breakpoints.ordered_breakpoint_keys(script) == ["日·车内#0"]


def test_a_blank_tail_is_not_a_segment() -> None:
    script = {
        "scenes": [
            {
                "heading": "夜·巷口",
                "blocks": [
                    {"type": "action", "text": "他停下", "character": None},
                    {"type": "breakpoint", "text": "切", "character": None},
                    {"type": "action", "text": "   ", "character": None},
                ],
            }
        ]
    }
    assert breakpoints.ordered_breakpoint_keys(script) == ["夜·巷口#0"]


def test_dialogue_keys_and_segment_lookup() -> None:
    script = {"scenes": [_scene("日·教室", "dialogue", "breakpoint", "dialogue")]}
    segments = breakpoints.ordered_segments(script)
    assert breakpoints.dialogue_line_key("日·教室", 2) == "日·教室#L2"
    first = breakpoints.segment_containing(segments, 0, 0)
    second = breakpoints.segment_containing(segments, 0, 2)
    assert first is not None and first.key == "日·教室#0"
    assert second is not None and second.key == "日·教室#1"
    assert breakpoints.segment_containing(segments, 1, 0) is None
