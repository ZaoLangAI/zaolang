"""Camera poses for multi-angle ("机位") library images.

One closed grid shared by every reader: the job params (`camera_poses`),
the fal multi-angle adapter (`to_fal`), the prompt-only fallback
(`to_prompt_phrase`), slot filing (`bucket`) and reference ranking
(`angular_distance`). The grid is the one the fal
`qwen-image-edit-2511-multiple-angles` LoRA was trained on: 8 azimuths ×
4 elevations × 3 distances (96 poses).

Azimuth is measured around the subject, camera-relative: 0 = the subject's
front faces the camera, 90 = the camera sits at the subject's right (we see
its right side), 180 = its back, 270 = its left. A scene uses the same
numbers relative to its master plate's camera, so 180 is the reverse shot
(反打).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

CameraDistance = Literal["close", "medium", "wide"]

AZIMUTHS: tuple[int, ...] = (0, 45, 90, 135, 180, 225, 270, 315)
ELEVATIONS: tuple[int, ...] = (-30, 0, 30, 60)
DISTANCES: tuple[CameraDistance, ...] = get_args(CameraDistance)
MAX_CAMERA_POSES = 8

# fal `zoom` is 0 (wide) … 10 (close-up); 5 is its own "medium" default.
_FAL_ZOOM: dict[str, float] = {"close": 8.0, "medium": 5.0, "wide": 2.0}

_AZIMUTH_LABELS: dict[int, str] = {
    0: "正面",
    45: "右前侧",
    90: "右侧",
    135: "右后侧",
    180: "背面",
    225: "左后侧",
    270: "左侧",
    315: "左前侧",
}
_ELEVATION_LABELS: dict[int, str] = {-30: "仰拍", 0: "平视", 30: "俯拍", 60: "高位俯拍"}
_DISTANCE_LABELS: dict[str, str] = {"close": "特写", "medium": "中景", "wide": "远景"}
_ELEVATION_PHRASES: dict[int, str] = {
    -30: "低机位仰拍",
    0: "平视机位",
    30: "略高机位俯拍",
    60: "高机位大俯拍",
}


@dataclass(frozen=True, slots=True)
class CameraPose:
    azimuth: int
    elevation: int = 0
    distance: CameraDistance = "medium"

    def bucket(self) -> tuple[int, int, str]:
        """The slot key: snapped to the trained grid."""
        snapped = snap(self)
        return (snapped.azimuth, snapped.elevation, snapped.distance)

    def as_dict(self) -> dict[str, Any]:
        return {"azimuth": self.azimuth, "elevation": self.elevation, "distance": self.distance}


def snap(pose: CameraPose) -> CameraPose:
    """Nearest pose on the trained grid (a panorama capture's yaw/pitch is
    arbitrary; a slot and a fal call are not)."""
    azimuth = min(AZIMUTHS, key=lambda a: _azimuth_gap(a, pose.azimuth % 360))
    elevation = min(ELEVATIONS, key=lambda e: abs(e - pose.elevation))
    distance: CameraDistance = pose.distance if pose.distance in DISTANCES else "medium"
    return CameraPose(azimuth=azimuth, elevation=elevation, distance=distance)


def parse(raw: Any) -> CameraPose | None:
    """A stored/request `{azimuth, elevation, distance}` mapping, or `None`
    for anything malformed (old rows, client junk) — never raises."""
    if not isinstance(raw, Mapping):
        return None
    try:
        azimuth = int(raw.get("azimuth"))  # type: ignore[arg-type]
        elevation = int(raw.get("elevation", 0))
    except (TypeError, ValueError):
        return None
    distance = raw.get("distance", "medium")
    if distance not in DISTANCES:
        distance = "medium"
    return CameraPose(
        azimuth=azimuth % 360, elevation=max(-30, min(90, elevation)), distance=distance
    )


def label_zh(pose: CameraPose) -> str:
    snapped = snap(pose)
    return "·".join(
        (
            f"{_AZIMUTH_LABELS[snapped.azimuth]} {snapped.azimuth}°",
            _ELEVATION_LABELS[snapped.elevation],
            _DISTANCE_LABELS[snapped.distance],
        )
    )


def to_fal(pose: CameraPose) -> dict[str, float]:
    """fal multi-angle request fields."""
    return {
        "horizontal_angle": float(pose.azimuth % 360),
        "vertical_angle": float(max(-30, min(90, pose.elevation))),
        "zoom": _FAL_ZOOM.get(pose.distance, 5.0),
    }


def to_prompt_phrase(pose: CameraPose) -> str:
    """The same move in words, for a model with no camera control."""
    snapped = snap(pose)
    azimuth = snapped.azimuth
    if azimuth == 0:
        turn = "保持正面机位"
    elif azimuth == 180:
        turn = "将镜头绕主体旋转180度，拍摄主体背面"
    elif azimuth < 180:
        turn = f"将镜头绕主体向右旋转{azimuth}度"
    else:
        turn = f"将镜头绕主体向左旋转{360 - azimuth}度"
    return f"{turn}，{_ELEVATION_PHRASES[snapped.elevation]}，{_DISTANCE_LABELS[snapped.distance]}"


def from_view(view: str | None) -> CameraPose | None:
    """The pose an old coarse `view` value stands for (side = right side)."""
    return {
        "front": CameraPose(0),
        "side": CameraPose(90),
        "back": CameraPose(180),
        "three_quarter": CameraPose(45),
        "reverse": CameraPose(180),
    }.get(view or "")


def coarse_view(pose: CameraPose) -> str:
    """The legacy `view` value a pose files under for readers that only know
    front/side/back/three_quarter."""
    azimuth = snap(pose).azimuth
    if azimuth == 0:
        return "front"
    if azimuth == 180:
        return "back"
    if azimuth in {90, 270}:
        return "side"
    return "three_quarter"


_SIDE_AZIMUTH: dict[str, int] = {
    "front": 0,
    "right": 90,
    "back": 180,
    "left": 270,
    # Over-the-shoulder looks past the near character at the subject's
    # three-quarter front.
    "ots_left": 315,
    "ots_right": 45,
}
_HEIGHT_ELEVATION: dict[str, int] = {
    "ground": -30,
    "low": -30,
    "eye": 0,
    "high": 30,
    "overhead": 60,
}
_SIZE_DISTANCE: dict[str, CameraDistance] = {
    "extreme_close": "close",
    "close": "close",
    "medium_close": "close",
    "medium": "medium",
    "full": "wide",
    "wide": "wide",
    "extreme_wide": "wide",
}


def from_blocking(
    side: str | None, height: str | None = None, size: str | None = None
) -> CameraPose | None:
    """A blocking/script shot's `side`/`height`/`size` as a pose; `None`
    when the shot names no side (height alone cannot pick an image)."""
    if side not in _SIDE_AZIMUTH and height not in _HEIGHT_ELEVATION:
        return None
    return CameraPose(
        azimuth=_SIDE_AZIMUTH.get(side or "", 0),
        elevation=_HEIGHT_ELEVATION.get(height or "", 0),
        distance=_SIZE_DISTANCE.get(size or "", "medium"),
    )


def _azimuth_gap(a: int, b: int) -> int:
    gap = abs(a - b) % 360
    return min(gap, 360 - gap)


def angular_distance(a: CameraPose, b: CameraPose) -> float:
    """How far apart two viewpoints are, for ranking references: azimuth
    gap in degrees plus the elevation gap at half weight (a side view at eye
    level beats a front view from above for a side shot)."""
    return _azimuth_gap(a.azimuth, b.azimuth) + abs(a.elevation - b.elevation) * 0.5
