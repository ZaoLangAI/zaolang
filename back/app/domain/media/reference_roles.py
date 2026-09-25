"""What a reference *means* to the video model, beyond "here is a file".

Today one role: a 白膜 (3D blockout) render passed as a motion guide
(`VideoGenerationOptions.reference_video_role == "motion_guide"`). The clip
shows grey primitive sets and flat-coloured mannequins, so without being
told otherwise a reference-to-video model tends to reproduce exactly that.
The directive below is prepended to the prompt at generation time
(`app.workflows.nodes._plan_enhancements`), the matching negative terms are
appended, and both stay out of the author's own stored prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MOTION_GUIDE = "motion_guide"

MOTION_GUIDE_DIRECTIVE = (
    "参考视频是这段镜头的白膜预演：严格沿用其中的机位、景别、运镜轨迹与速度、人物站位与走位、"
    "动作节奏和时长；画面中的灰白几何体只代表场景结构与陈设的位置和大小，彩色人偶只代表角色的位置"
    "和姿态。人物的外貌、服装与场景的材质、光线、色彩一律以参考图片和下面的描述为准，"
    "不要出现灰白模型、几何体、人偶或文字标签。"
)
MOTION_GUIDE_NEGATIVE = "灰白模型，低多边形，人偶，几何体占位，名字标签，文字"


def is_motion_guide(video_options: Any) -> bool:
    return isinstance(video_options, Mapping) and (
        video_options.get("reference_video_role") == MOTION_GUIDE
    )


def apply_reference_roles(
    prompt: str, negative_prompt: str | None, video_options: Any
) -> tuple[str, str | None]:
    if not is_motion_guide(video_options):
        return prompt, negative_prompt
    guided = f"{MOTION_GUIDE_DIRECTIVE}\n{prompt}" if prompt else MOTION_GUIDE_DIRECTIVE
    negative = (
        f"{negative_prompt}，{MOTION_GUIDE_NEGATIVE}" if negative_prompt else MOTION_GUIDE_NEGATIVE
    )
    return guided, negative
