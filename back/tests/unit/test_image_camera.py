"""Camera-pose vocabulary for multi-angle library images."""

from __future__ import annotations

from app.domain.image_assets import camera
from app.domain.image_assets.camera import CameraPose


def test_snap_lands_on_the_trained_grid() -> None:
    assert camera.snap(CameraPose(100, 12, "close")) == CameraPose(90, 0, "close")
    assert camera.snap(CameraPose(350, -40, "wide")) == CameraPose(0, -30, "wide")
    assert CameraPose(200, 50).bucket() == (180, 60, "medium")


def test_parse_tolerates_junk() -> None:
    assert camera.parse({"azimuth": 450, "elevation": 120}) == CameraPose(90, 90, "medium")
    assert camera.parse({"azimuth": "x"}) is None
    assert camera.parse(None) is None
    assert camera.parse({"azimuth": 45, "distance": "far"}) == CameraPose(45, 0, "medium")


def test_fal_fields_and_prompt_phrase() -> None:
    pose = CameraPose(270, 30, "close")
    assert camera.to_fal(pose) == {"horizontal_angle": 270.0, "vertical_angle": 30.0, "zoom": 8.0}
    assert camera.to_prompt_phrase(pose) == "将镜头绕主体向左旋转90度，略高机位俯拍，特写"
    assert "背面" in camera.to_prompt_phrase(CameraPose(180))
    assert camera.label_zh(CameraPose(90)) == "右侧 90°·平视·中景"


def test_views_and_blocking_map_to_poses() -> None:
    assert camera.from_view("side") == CameraPose(90)
    assert camera.from_view("back") == CameraPose(180)
    assert camera.from_view("general") is None
    assert camera.coarse_view(CameraPose(270)) == "side"
    assert camera.coarse_view(CameraPose(315)) == "three_quarter"
    assert camera.from_blocking("back", "high", "full") == CameraPose(180, 30, "wide")
    assert camera.from_blocking(None, None, "close") is None


def test_angular_distance_wraps_and_weights_elevation() -> None:
    assert camera.angular_distance(CameraPose(350 // 45 * 45), CameraPose(0)) == 45
    assert camera.angular_distance(CameraPose(315), CameraPose(45)) == 90
    side_eye = camera.angular_distance(CameraPose(90), CameraPose(90, 30))
    front_eye = camera.angular_distance(CameraPose(0), CameraPose(90, 30))
    assert side_eye < front_eye
