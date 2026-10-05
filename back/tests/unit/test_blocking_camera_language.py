"""`app.domain.blocking.camera_language` — the script's camera grammar
(「景别，速度＋方向＋方式」) read without a model."""

from __future__ import annotations

import pytest

from app.domain.blocking import vocabulary as v
from app.domain.blocking.camera_language import normalize_token, parse_camera_text


@pytest.mark.parametrize(
    ("text", "size", "preset", "intensity"),
    [
        ("中近景，固定机位。", "medium_close", "static", 0.5),
        ("特写，缓慢向前推。", "close", "push_in", 0.3),
        ("近景，缓慢向右摇。", "close", "pan_right", 0.3),
        ("全景，缓慢向上抬升。", "full", "crane_up", 0.3),
        ("中景，快速向左平移", "medium", "truck_left", 0.8),
        ("远景，镜头缓缓拉远", "wide", "pull_out", 0.3),
        ("中近景，向上摇至天花板", "medium_close", "tilt_up", 0.5),
        ("中景，跟拍林夏走向门口", "medium", "follow", 0.5),
        ("全景，逆时针环绕两人", "full", "orbit_ccw", 0.5),
        ("中景，环绕", "medium", "orbit_cw", 0.5),
        ("大特写，手持轻微晃动", "extreme_close", "handheld", 0.3),
        ("大远景", "extreme_wide", None, 0.5),
    ],
)
def test_script_camera_blocks_parse(
    text: str, size: str, preset: str | None, intensity: float
) -> None:
    cue = parse_camera_text(text)
    assert (cue.size, cue.preset, cue.intensity) == (size, preset, intensity)


@pytest.mark.parametrize(
    ("raw", "kind", "allowed", "expected"),
    [
        ("push_in", "move", v.CAMERA_MOVES, "push_in"),
        ("Push-In", "move", v.CAMERA_MOVES, "push_in"),
        ("dolly out", "move", v.CAMERA_MOVES, "pull_out"),
        ("推", "move", v.CAMERA_MOVES, "push_in"),
        ("缓慢左摇", "move", v.CAMERA_MOVES, "pan_left"),
        ("ECU", "size", v.SHOT_SIZES, "extreme_close"),
        ("中近景", "size", v.SHOT_SIZES, "medium_close"),
        ("over the shoulder right", "side", v.CAMERA_SIDES, "ots_right"),
        ("平视", "height", v.CAMERA_HEIGHTS, "eye"),
        ("说话", "action", v.CAST_ACTIONS, "talk"),
        ("teleport", "move", v.CAMERA_MOVES, None),
        (None, "size", v.SHOT_SIZES, None),
    ],
)
def test_vendor_tokens_normalize(
    raw: object, kind: str, allowed: tuple[str, ...], expected: str | None
) -> None:
    assert normalize_token(raw, allowed, kind) == expected


def test_side_and_height_are_read_from_camera_text() -> None:
    from app.domain.blocking.camera_language import parse_camera_text

    back = parse_camera_text("全景，背影，缓慢推进")
    assert (back.size, back.side, back.height) == ("full", "back", None)
    assert parse_camera_text("中景，左侧面平视").side == "left"
    assert parse_camera_text("近景，侧脸").side == "right"
    assert parse_camera_text("过肩镜头，越过男主右肩").side == "ots_right"
    assert parse_camera_text("大全景，鸟瞰").height == "overhead"
    assert parse_camera_text("仰拍，缓慢上摇").height == "low"
    # Where someone stands in frame is not a camera side.
    assert parse_camera_text("中景，人物站在画面左侧").side is None
