"""Deterministic reading of camera language — the script's own `camera`
blocks, and loose model tokens.

`copywriter._BLOCK_TYPE_RULES` already makes every script `camera` block
follow one grammar: shot size first, then *how, which way, how fast*
(「中近景，缓慢向左平移」). That makes the script's camera direction
machine-readable, so the blockout does not have to trust a model to
translate it: `parse_camera_text` reads it, `sanitize` reconciles the
model's shots against it, and the derive prompt is handed the parsed cues.

`normalize_token` is the other half of provider tolerance: models answer
with the documented token, the Chinese label, a film-school abbreviation
(`MCU`, `dolly in`) or a near miss (`push-in`), depending on vendor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.blocking import vocabulary as v

# Longest first: 「中近景」 must not read as 「近景」, 「大特写」 not as 「特写」.
_SIZE_WORDS: tuple[tuple[str, str], ...] = (
    ("大远景", "extreme_wide"),
    ("超远景", "extreme_wide"),
    ("大全景", "extreme_wide"),
    ("中近景", "medium_close"),
    ("近中景", "medium_close"),
    ("大特写", "extreme_close"),
    ("远景", "wide"),
    ("全景", "full"),
    ("中景", "medium"),
    ("特写", "close"),
    ("近景", "close"),
)

_SLOW = re.compile(r"缓慢|缓缓|慢慢|轻微|轻轻|微微|徐徐|缓")
_FAST = re.compile(r"快速|迅速|急速|猛然|猛地|快|急|甩")

# Order matters: the first rule that matches wins, and 「上摇」 (tilt) must be
# read before 「上升」 (crane), 「推」 before bare direction words, etc.
_MOVE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"固定|静止|定镜|不动|定格"), "static"),
    (re.compile(r"手持|晃动|摇晃|抖动"), "handheld"),
    (re.compile(r"逆时针.{0,4}(环绕|绕)|(环绕|绕).{0,4}逆时针|向左.{0,2}(环绕|绕)"), "orbit_ccw"),
    (re.compile(r"环绕|绕拍|绕.{0,2}(转|拍)|旋转.{0,2}镜头|顺时针"), "orbit_cw"),
    (re.compile(r"跟拍|跟随|跟镜|跟摄|跟着|尾随"), "follow"),
    (re.compile(r"(向)?(左|往左).{0,2}(摇|摇摄|甩)"), "pan_left"),
    (re.compile(r"(向)?(右|往右).{0,2}(摇|摇摄|甩)"), "pan_right"),
    (re.compile(r"(向)?(上|往上).{0,2}(摇|仰)|上摇|仰拍.{0,2}摇"), "tilt_up"),
    (re.compile(r"(向)?(下|往下).{0,2}(摇|俯)|下摇"), "tilt_down"),
    (re.compile(r"(向)?(左|往左).{0,2}(平移|横移|侧移|移|滑)"), "truck_left"),
    (re.compile(r"(向)?(右|往右).{0,2}(平移|横移|侧移|移|滑)"), "truck_right"),
    (re.compile(r"升起|上升|抬升|升高|拔高|升镜|摇臂.{0,2}升|升"), "crane_up"),
    (re.compile(r"下降|降下|降低|降镜|摇臂.{0,2}降|落下|降"), "crane_down"),
    (re.compile(r"推进|推近|推向|前推|推镜|向前推|推"), "push_in"),
    (re.compile(r"拉远|拉开|后拉|拉镜|向后拉|拉出|拉"), "pull_out"),
    (re.compile(r"(平移|横移|侧移|移动)"), "truck_right"),
    (re.compile(r"摇"), "pan_right"),
)


# Which side of the subject the camera sees (`vocabulary.CameraSide`) and
# how high it sits (`CameraHeight`) — read so a shot's references can match
# its angle (`asset_variants.ReferenceHints`, AC-3). First match wins.
_SIDE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"过肩.{0,8}右|右.{0,3}过肩"), "ots_right"),
    (re.compile(r"过肩"), "ots_left"),
    (re.compile(r"背影|背面|背对|背身|身后|后背|从后方|后方拍"), "back"),
    (re.compile(r"左侧(面|脸|身|拍)|从左侧|左边侧面"), "left"),
    (re.compile(r"右侧(面|脸|身|拍)|从右侧|右边侧面"), "right"),
    (re.compile(r"侧面|侧脸|侧身|侧拍|侧影|侧写"), "right"),
    (re.compile(r"正面|正脸|正对|迎面"), "front"),
)
_HEIGHT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"鸟瞰|顶拍|顶视|俯瞰|正上方"), "overhead"),
    (re.compile(r"俯拍|俯视|俯角|高机位|居高"), "high"),
    (re.compile(r"贴地|地面机位|极低"), "ground"),
    (re.compile(r"仰拍|仰视|仰角|低机位|低角度"), "low"),
    (re.compile(r"平视|平拍"), "eye"),
)


@dataclass(frozen=True, slots=True)
class CameraCue:
    size: str | None
    preset: str | None
    intensity: float
    side: str | None = None
    height: str | None = None

    @property
    def empty(self) -> bool:
        return self.size is None and self.preset is None


def parse_camera_text(text: str) -> CameraCue:
    """One script camera block → shot size, move preset, speed, and the
    side / height the camera sees the subject from."""
    text = str(text or "")
    size = next((token for word, token in _SIZE_WORDS if word in text), None)
    preset = next((token for pattern, token in _MOVE_RULES if pattern.search(text)), None)
    if preset in (None, "static"):
        intensity = 0.5
    elif _SLOW.search(text):
        intensity = 0.3
    elif _FAST.search(text):
        intensity = 0.8
    else:
        intensity = 0.5
    side = next((token for pattern, token in _SIDE_RULES if pattern.search(text)), None)
    height = next((token for pattern, token in _HEIGHT_RULES if pattern.search(text)), None)
    return CameraCue(size=size, preset=preset, intensity=intensity, side=side, height=height)


def _reverse(labels: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for token, label in labels.items():
        for part in re.split(r"[/（）()、，,]", label):
            part = part.strip()
            if part and part not in result:
                result[part] = token
    return result


# Aliases a model plausibly emits instead of the documented token.
SYNONYMS: dict[str, dict[str, str]] = {
    "size": {
        "ecu": "extreme_close",
        "extreme_close_up": "extreme_close",
        "extreme_closeup": "extreme_close",
        "cu": "close",
        "close_up": "close",
        "closeup": "close",
        "mcu": "medium_close",
        "medium_close_up": "medium_close",
        "medium_closeup": "medium_close",
        "ms": "medium",
        "mid": "medium",
        "medium_shot": "medium",
        "fs": "full",
        "full_shot": "full",
        "ls": "wide",
        "long": "wide",
        "long_shot": "wide",
        "wide_shot": "wide",
        "ws": "wide",
        "els": "extreme_wide",
        "extreme_long": "extreme_wide",
        "extreme_long_shot": "extreme_wide",
        "ews": "extreme_wide",
        **_reverse(v.SHOT_SIZE_LABELS),
    },
    "move": {
        "fixed": "static",
        "still": "static",
        "locked": "static",
        "dolly_in": "push_in",
        "push": "push_in",
        "zoom_in": "push_in",
        "track_in": "push_in",
        "dolly_out": "pull_out",
        "pull": "pull_out",
        "pull_back": "pull_out",
        "zoom_out": "pull_out",
        "track_out": "pull_out",
        "pan": "pan_right",
        "tilt": "tilt_up",
        "truck": "truck_right",
        "track_left": "truck_left",
        "track_right": "truck_right",
        "tracking": "follow",
        "track": "follow",
        "follow_shot": "follow",
        "orbit": "orbit_cw",
        "arc": "orbit_cw",
        "arc_left": "orbit_ccw",
        "arc_right": "orbit_cw",
        "crane": "crane_up",
        "pedestal_up": "crane_up",
        "pedestal_down": "crane_down",
        "boom_up": "crane_up",
        "boom_down": "crane_down",
        "shaky": "handheld",
        "hand_held": "handheld",
        **_reverse(v.CAMERA_MOVE_LABELS),
    },
    "height": {
        "eye_level": "eye",
        "low_angle": "low",
        "high_angle": "high",
        "birds_eye": "overhead",
        "top": "overhead",
        "top_down": "overhead",
        "worms_eye": "ground",
        **_reverse(v.CAMERA_HEIGHT_LABELS),
    },
    "side": {
        "frontal": "front",
        "profile_left": "left",
        "profile_right": "right",
        "rear": "back",
        "behind": "back",
        "ots": "ots_left",
        "over_shoulder": "ots_left",
        "over_the_shoulder": "ots_left",
        "over_shoulder_left": "ots_left",
        "over_shoulder_right": "ots_right",
        "over_the_shoulder_left": "ots_left",
        "over_the_shoulder_right": "ots_right",
        **_reverse(v.CAMERA_SIDE_LABELS),
    },
    "action": {
        "idle": "stand",
        "standing": "stand",
        "sitting": "sit",
        "seated": "sit",
        "walking": "walk",
        "running": "run",
        "speak": "talk",
        "speaking": "talk",
        "talking": "talk",
        "say": "talk",
        "gesture": "talk",
        "pointing": "point",
        "waving": "wave",
        "crouch": "kneel",
        "squat": "kneel",
        "kneeling": "kneel",
        "lie": "fall",
        "lying": "fall",
        "collapse": "fall",
        "pick_up": "pickup",
        "grab": "pickup",
        "embrace": "hug",
        "push": "fight",
        "punch": "fight",
        "struggle": "fight",
        "turn_around": "turn",
        "look": "turn",
        **_reverse(v.CAST_ACTION_LABELS),
    },
}


def normalize_token(raw: object, allowed: tuple[str, ...], kind: str) -> str | None:
    """The documented token for a loose model value, or `None`."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in allowed:
        return text
    key = re.sub(r"[\s\-]+", "_", text.lower())
    if key in allowed:
        return key
    aliases = SYNONYMS.get(kind, {})
    for candidate in (key, text):
        mapped = aliases.get(candidate)
        if mapped in allowed:
            return mapped
    # A Chinese phrase («缓慢推近», «中近景镜头») rather than a bare label.
    if kind in ("size", "move"):
        cue = parse_camera_text(text)
        token = cue.size if kind == "size" else cue.preset
        if token in allowed:
            return token
    return None
