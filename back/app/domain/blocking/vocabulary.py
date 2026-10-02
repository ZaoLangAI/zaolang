"""The closed vocabularies a blocking document is written in.

One source of truth for three readers: the Pydantic response models (and
through `make openapi` the frontend's TS unions), the sanitizer, and the
`blocking_derive` system prompt — so a preset the model is told about is
always one the sanitizer keeps and the compiler can play.
"""

from __future__ import annotations

from typing import Literal, get_args

BlockingAspectRatio = Literal["9:16", "16:9", "1:1"]
Ground = Literal["floor", "street", "grass", "sand", "water", "void"]
Primitive = Literal["box", "plane", "cylinder", "sphere", "cone", "capsule", "torus", "stairs"]
ColorRole = Literal["wall", "floor", "furniture", "door", "window", "vehicle", "nature", "accent"]
CastAction = Literal[
    "stand",
    "sit",
    "walk",
    "run",
    "turn",
    "point",
    "talk",
    "wave",
    "kneel",
    "fall",
    "pickup",
    "hug",
    "fight",
]
ShotSize = Literal[
    "extreme_wide", "wide", "full", "medium", "medium_close", "close", "extreme_close"
]
CameraHeight = Literal["ground", "low", "eye", "high", "overhead"]
CameraSide = Literal["front", "left", "right", "back", "ots_left", "ots_right"]
CameraMove = Literal[
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "truck_left",
    "truck_right",
    "follow",
    "orbit_cw",
    "orbit_ccw",
    "crane_up",
    "crane_down",
    "handheld",
]
MoveEase = Literal["linear", "in_out"]
# How a shot begins relative to the one before it inside the same segment:
# a hard `cut`, or a `continuous` camera move from the previous framing.
ShotTransition = Literal["cut", "continuous"]
BlockingOrigin = Literal["llm_turn", "rebuild", "manual"]

ASPECT_RATIOS: tuple[str, ...] = get_args(BlockingAspectRatio)
GROUNDS: tuple[str, ...] = get_args(Ground)
PRIMITIVES: tuple[str, ...] = get_args(Primitive)
COLOR_ROLES: tuple[str, ...] = get_args(ColorRole)
CAST_ACTIONS: tuple[str, ...] = get_args(CastAction)
SHOT_SIZES: tuple[str, ...] = get_args(ShotSize)
CAMERA_HEIGHTS: tuple[str, ...] = get_args(CameraHeight)
CAMERA_SIDES: tuple[str, ...] = get_args(CameraSide)
CAMERA_MOVES: tuple[str, ...] = get_args(CameraMove)
MOVE_EASES: tuple[str, ...] = get_args(MoveEase)
SHOT_TRANSITIONS: tuple[str, ...] = get_args(ShotTransition)

# Chinese glosses the `blocking_derive` prompt pairs with each token, so the
# model maps the script's own camera language (「缓慢推近」) onto a preset
# instead of inventing a token the sanitizer would drop.
CAST_ACTION_LABELS: dict[str, str] = {
    "stand": "站立",
    "sit": "坐下/坐着",
    "walk": "行走（配合 to 移动）",
    "run": "奔跑（配合 to 移动）",
    "turn": "转身",
    "point": "指向",
    "talk": "说话（带手势）",
    "wave": "挥手",
    "kneel": "跪下/蹲下",
    "fall": "倒地",
    "pickup": "弯腰拾取",
    "hug": "拥抱",
    "fight": "推搡/打斗",
}
SHOT_SIZE_LABELS: dict[str, str] = {
    "extreme_wide": "大远景",
    "wide": "远景",
    "full": "全景",
    "medium": "中景",
    "medium_close": "中近景",
    "close": "近景/特写",
    "extreme_close": "大特写",
}
CAMERA_HEIGHT_LABELS: dict[str, str] = {
    "ground": "贴地",
    "low": "低机位仰拍",
    "eye": "平视",
    "high": "高机位俯拍",
    "overhead": "顶拍",
}
CAMERA_SIDE_LABELS: dict[str, str] = {
    "front": "正面",
    "left": "左侧",
    "right": "右侧",
    "back": "背面",
    "ots_left": "过左肩（over 为前景肩膀所属角色）",
    "ots_right": "过右肩（over 为前景肩膀所属角色）",
}
CAMERA_MOVE_LABELS: dict[str, str] = {
    "static": "固定",
    "push_in": "推",
    "pull_out": "拉",
    "pan_left": "左摇",
    "pan_right": "右摇",
    "tilt_up": "上摇",
    "tilt_down": "下摇",
    "truck_left": "左移",
    "truck_right": "右移",
    "follow": "跟拍",
    "orbit_cw": "顺时针环绕",
    "orbit_ccw": "逆时针环绕",
    "crane_up": "升",
    "crane_down": "降",
    "handheld": "手持晃动",
}

# Eight fixed cast colours; the frontend's palette module maps the index to
# a theme token and a colour *name*, which is what the video prompt's cast
# legend ("红色人偶 = 林夏") quotes.
CAST_COLOR_COUNT = 8

# Segment length window. The low end is the shortest clip every
# reference-video-capable model accepts (H3/fal h3-max floor at 4–5s); the
# high end is `VIDEO_MAX_DURATION_SECONDS`, which `GenerationParams` enforces
# once `video_options` is present.
SEGMENT_MIN_SECONDS = 5
SEGMENT_MAX_SECONDS = 15

MAX_SETS = 40
MAX_PROPS_PER_SET = 40
MAX_ANCHORS_PER_SET = 24
MAX_CAST = 8
MAX_SEGMENTS = 120
MAX_BEATS_PER_SEGMENT = 16
# A segment is one generated clip, but the camera may change inside it —
# one shot per script `camera` block, typically.
MAX_SHOTS_PER_SEGMENT = 6
MIN_SHOT_SECONDS = 1.0
MAX_ID_LEN = 24
MAX_LABEL_LEN = 20
STAGE_MIN_METERS = 4.0
STAGE_MAX_METERS = 60.0
LENS_MIN_MM = 14
LENS_MAX_MM = 135
CAST_MIN_HEIGHT_M = 1.0
CAST_MAX_HEIGHT_M = 2.1
TARGET_DURATION_MAX_SECONDS = 1800
