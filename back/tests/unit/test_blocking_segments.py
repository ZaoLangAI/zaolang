"""`app.domain.blocking.segments` — keying must agree with the frontend's
`orderedBreakpointKeys` (`front/src/features/script/script-breakpoint.test.ts`
pins the same three cases), since a blocking segment and a generated clip
bind to the same `{heading}#{ordinal}`."""

from __future__ import annotations

from typing import Any

from app.domain.blocking.segments import (
    default_target_duration,
    estimate_segment_seconds,
    ordered_segments,
    script_hash,
    segment_source_hash,
)


def _scene(heading: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"heading": heading, "ref_id": None, "blocks": blocks}


def _cut(text: str = "cut") -> dict[str, Any]:
    return {"type": "breakpoint", "character": None, "text": text}


def _script(*scenes: dict[str, Any]) -> dict[str, Any]:
    return {"title": "", "logline": "", "characters": [], "scenes": list(scenes)}


def test_keys_flatten_breakpoints_in_document_order() -> None:
    script = _script(_scene("场A", [_cut(), _cut()]), _scene("场B", [_cut()]))
    assert [s.key for s in ordered_segments(script)] == ["场A#0", "场A#1", "场B#0"]


def test_trailing_unclosed_segment_is_the_scenes_last_key() -> None:
    action = {"type": "action", "character": None, "text": "开门"}
    script = _script(_scene("监听室", [_cut(), action]))
    segments = ordered_segments(script)
    assert [s.key for s in segments] == ["监听室#0", "监听室#1"]
    assert segments[1].blocks == (action,)


def test_scene_with_no_breakpoint_and_no_content_has_no_segment() -> None:
    assert ordered_segments(_script(_scene("空场", []))) == []


def test_segment_blocks_exclude_the_breakpoint_itself() -> None:
    line = {"type": "dialogue", "character": "林夏", "text": "走吧。"}
    segments = ordered_segments(_script(_scene("场", [line, _cut()])))
    assert segments[0].blocks == (line,)


def test_estimate_follows_dialogue_rate_and_clamps_to_the_segment_window() -> None:
    short = [{"type": "dialogue", "character": "A", "text": "好"}]
    assert estimate_segment_seconds(short) == 5.0
    long_line = [{"type": "dialogue", "character": "A", "text": "字" * 200}]
    assert estimate_segment_seconds(long_line) == 15.0
    # Stage directions in brackets are not spoken.
    bracketed = [{"type": "dialogue", "character": "A", "text": "（冷笑）" + "字" * 28}]
    assert estimate_segment_seconds(bracketed) == 8.0
    wide = [{"type": "camera", "character": None, "text": "远景，固定机位"}]
    assert estimate_segment_seconds(wide) == 10.0


def test_default_target_sums_the_estimates() -> None:
    script = _script(
        _scene("场", [{"type": "action", "character": None, "text": "推门"}, _cut()]),
        _scene("场2", [{"type": "camera", "character": None, "text": "全景"}]),
    )
    assert default_target_duration(script) == 5 + 8


def test_hashes_ignore_links_and_traits_but_see_block_edits() -> None:
    base = _script(_scene("场", [{"type": "action", "character": None, "text": "推门"}]))
    base["characters"] = [{"name": "林夏", "traits": "a", "character_ref_id": None}]
    linked = {
        **base,
        "characters": [{"name": "林夏", "traits": "b", "character_ref_id": "chr_1"}],
        "scenes": [{**base["scenes"][0], "ref_id": "scn_1"}],
    }
    assert script_hash(base) == script_hash(linked)

    edited = _script(_scene("场", [{"type": "action", "character": None, "text": "撞门"}]))
    edited["characters"] = base["characters"]
    assert script_hash(base) != script_hash(edited)
    assert segment_source_hash(ordered_segments(base)[0]) != segment_source_hash(
        ordered_segments(edited)[0]
    )
