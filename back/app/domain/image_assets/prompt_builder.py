"""Server-side prompt assembly for character/scene image passes.

`app.workflows.nodes.execute_asset_planning` used to carry the fixed
fragments inline (sheet layout, completion override, medium lock); they live
here now next to the expression/scene-preset text built from
`vocabulary`, so every pass is composed in one deterministic order:

    [fixed instruction tied to reference 1] [caller prompt] [presets / layout] [medium]

Everything here is pure string work — no session, no context object — so it
is unit-testable on its own and the planner's optional additions can only
ever append to it (`sanitize_enhancements` drops the ones that would
contradict the pass, since a published `AgentSkill` can override every
system-prompt rule).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from app.domain.image_assets.vocabulary import (
    EXPRESSION_PRESETS,
    PERIOD_PRESETS,
    SCENE_PRESET_AXES,
    SCENE_PRESET_TABLES,
    expression_grid,
    scene_preset_label,
    scene_presets_from,
)
from app.models.enums import CharacterViewAngle, ImageAssetKind


class AssetPass(StrEnum):
    """What one `asset_planning` pass is producing."""

    CHARACTER_SHEET = "character_sheet"
    CHARACTER_COMPLETION = "character_completion"
    CHARACTER_EXPRESSIONS = "character_expressions"
    SCENE = "scene"
    SCENE_VARIANT_GROUP = "scene_variant_group"
    OTHER = "other"


# The intent for a side/back completion pass — deliberately *not* whatever
# free-text prompt the caller sent. The front reference image is forwarded
# unchanged into every loop pass via `reference_asset_ids`; the only thing
# this instruction does is tell the model to use that image as material, so
# it never competes with a caller's own (possibly inconsistent) description.
#
# Keyed per view rather than one shared "侧面/背面" string: an ambiguous slash
# nudged the model toward producing both angles in one image.
CHARACTER_COMPLETION_FIXED_PROMPTS: dict[str, str] = {
    CharacterViewAngle.SIDE.value: "参考本图生成侧面图",
    CharacterViewAngle.BACK.value: "参考本图生成背面图",
}

# Guaranteed regardless of what the planner suggests — a real completion job
# came back as a labelled multi-panel turnaround sheet without it.
CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT = (
    "多视角拼接图、对比图、分格或并排画面、同一画面出现两个以上角度、画面中出现视角文字标注"
    "（如FRONT VIEW/SIDE VIEW/BACK VIEW）"
)

# Appended on a CHARACTER `front` pass (the library / script-studio sheet
# job). Never replaces the caller's identity prompt and never runs on a
# completion or expression pass.
CHARACTER_SHEET_LAYOUT_SUFFIX = (
    "输出必须是一张专业角色设定图（单张画面，不要拆成多张）："
    "左侧从左到右全身三视图（正面、侧面、背面），纯白背景、全身站姿、不裁切头脚；"
    "右侧为面部多角度特写、服装面料与配饰细节、标准化色板；"
    "各分区为同一人物，严格保持五官、发型、服装与气质，禁止改设定、禁止额外角色或故事场景。"
)

# Visual-medium lock for a character sheet/expression pass. Script traits are
# supposed to lead with one shared medium; older scripts and free-typed
# prompts often omit it, and the model then picks photoreal for one cast
# member and anime for the next.
CHARACTER_PHOTOREAL_MEDIUM = "真人写实影视短剧造型"
CHARACTER_PHOTOREAL_NEGATIVE = "动漫、二次元、卡通、anime、illustration"
CHARACTER_ANIME_NEGATIVE = "真人照片、摄影棚写实"
_PHOTOREAL_MEDIUM_MARKERS = ("真人", "写实", "影视", "photoreal")
_ANIME_MEDIUM_MARKERS = ("动漫", "二次元", "anime", "插画")

# A 换装 sheet with the character's existing sheet attached as reference 1.
OUTFIT_CHANGE_PREFIX = (
    "以参考图1中的人物为准，严格保持其五官、发型发色、肤色、体型与身高比例完全一致，"
    "仅将服装替换为「{label}」造型："
)
OUTFIT_LABEL_SENTENCE = "本图为角色的「{label}」造型。"

EXPRESSION_IDENTITY_PREFIX = (
    "以参考图1中的人物为准，严格保持其五官、发型发色、肤色、服装与配饰完全一致。"
)
EXPRESSION_COMMON_NEGATIVE = (
    "文字、标签、编号、水印、不同的人、服装不一致、发型不一致、"
    "三视图、设定图、色板、全身像、复杂背景、故事场景"
)

SCENE_VARIANT_PREFIX = (
    "以参考图1为基准，保持建筑结构、门窗位置、机位、透视与陈设布局完全一致，仅改变：{label}。"
)
SCENE_GROUP_NEGATIVE = "拼接画面、分格、分屏、并排的多幅画面、多画面合成、画中画"

# Markers that only belong in a character sheet; an expression or a scene
# variant pass must never pick them up from the planner.
_SHEET_MARKERS = ("三视图", "设定图", "色板", "分栏", "turnaround")


def merge_negative(base: str | None, addition: str) -> str:
    if not addition:
        return base or ""
    if base and addition in base:
        return base
    return f"{base}，{addition}" if base else addition


def _join(prompt: str, addition: str, sep: str = "。") -> str:
    if not addition:
        return prompt
    if not prompt:
        return addition
    return f"{prompt.rstrip('。，, ')}{sep}{addition}"


def character_prompt_medium(text: str) -> str | None:
    """`'anime'` / `'photoreal'` / `None` when the prompt names no medium."""
    lowered = (text or "").lower()
    if any(marker.lower() in lowered for marker in _ANIME_MEDIUM_MARKERS):
        return "anime"
    if any(marker.lower() in lowered for marker in _PHOTOREAL_MEDIUM_MARKERS):
        return "photoreal"
    return None


def apply_visual_medium(prompt: str, negative: str | None) -> tuple[str, str]:
    """Locks a character pass to one visual medium.

    No named medium → default photoreal live-action and reject anime.
    Anime already named → keep it and reject photoreal. Photoreal already
    named → keep it and reject anime. Never rewrites an explicit medium.
    """
    medium = character_prompt_medium(prompt)
    if medium is None:
        prompt = _join(prompt, CHARACTER_PHOTOREAL_MEDIUM)
        medium = "photoreal"
    opposite = CHARACTER_ANIME_NEGATIVE if medium == "anime" else CHARACTER_PHOTOREAL_NEGATIVE
    return prompt, merge_negative(negative, opposite)


def _expressions(params: dict[str, Any]) -> list[str]:
    raw = params.get("character_expressions")
    if not isinstance(raw, list):
        return []
    return [str(key) for key in raw if str(key) in EXPRESSION_PRESETS]


def _scene_variants(params: dict[str, Any]) -> list[dict[str, str]]:
    raw = params.get("scene_variants")
    if not isinstance(raw, list):
        return []
    variants = [scene_presets_from(item) for item in raw if isinstance(item, dict)]
    return [variant for variant in variants if variant]


def resolve_pass(
    params: dict[str, Any], *, asset_kind: str | None, character_view: str | None
) -> AssetPass:
    if asset_kind == ImageAssetKind.CHARACTER.value:
        if character_view in CHARACTER_COMPLETION_FIXED_PROMPTS:
            return AssetPass.CHARACTER_COMPLETION
        if _expressions(params):
            return AssetPass.CHARACTER_EXPRESSIONS
        return AssetPass.CHARACTER_SHEET
    if asset_kind == ImageAssetKind.SCENE.value:
        if len(_scene_variants(params)) >= 2:
            return AssetPass.SCENE_VARIANT_GROUP
        return AssetPass.SCENE
    return AssetPass.OTHER


def compose(
    asset_pass: AssetPass,
    *,
    prompt: str,
    negative: str | None,
    params: dict[str, Any],
    character_view: str | None = None,
    has_reference: bool = False,
) -> tuple[str, str | None]:
    """The pass's prompt and negative prompt before the planner adds to them."""
    if asset_pass is AssetPass.CHARACTER_COMPLETION and character_view:
        return (
            CHARACTER_COMPLETION_FIXED_PROMPTS[character_view],
            merge_negative(negative, CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT),
        )
    if asset_pass is AssetPass.CHARACTER_SHEET:
        return _compose_character_sheet(prompt, negative, params, has_reference=has_reference)
    if asset_pass is AssetPass.CHARACTER_EXPRESSIONS:
        return _compose_expressions(prompt, negative, _expressions(params))
    if asset_pass is AssetPass.SCENE:
        return _compose_scene(
            prompt, negative, scene_presets_from(params), has_reference=has_reference
        )
    if asset_pass is AssetPass.SCENE_VARIANT_GROUP:
        return compose_scene_group(
            prompt, negative, _scene_variants(params), has_reference=has_reference
        )
    return prompt, negative


def _compose_character_sheet(
    prompt: str, negative: str | None, params: dict[str, Any], *, has_reference: bool
) -> tuple[str, str]:
    outfit = str(params.get("character_outfit_label") or "").strip()
    if outfit and has_reference:
        prompt = OUTFIT_CHANGE_PREFIX.format(label=outfit) + prompt
    elif outfit:
        prompt = _join(prompt, OUTFIT_LABEL_SENTENCE.format(label=outfit))
    if CHARACTER_SHEET_LAYOUT_SUFFIX not in prompt:
        prompt = _join(prompt, CHARACTER_SHEET_LAYOUT_SUFFIX)
    return apply_visual_medium(prompt, negative)


def expression_layout(expressions: list[str]) -> str:
    """The layout + per-cell sentence for a composite expression image."""
    if len(expressions) == 1:
        preset = EXPRESSION_PRESETS[expressions[0]]
        return (
            "输出一张单人头肩特写（单张画面），正面略侧，纯色浅灰背景，柔和均匀的正面光；"
            f"表情为{preset.prompt}。"
        )
    rows, cols = expression_grid(len(expressions))
    cells = "；".join(
        f"第{index}格{EXPRESSION_PRESETS[key].prompt}" for index, key in enumerate(expressions, 1)
    )
    leftover = "，最后一行的格子居中排列" if rows * cols > len(expressions) else ""
    return (
        f"输出一张角色表情合集图（单张画面，不要拆成多张）：共 {len(expressions)} 个等大分格，"
        f"排成 {rows} 行、每行最多 {cols} 格{leftover}；每格都是同一人物的头肩特写，"
        "机位、景别、角度与光线在各格之间保持一致，纯色浅灰背景；"
        f"从左到右、从上到下依次为：{cells}。"
        "所有格中的人物是同一个人，画面中不要出现任何文字、标签或编号。"
    )


_SHEET_SENTENCE = re.compile(r"[^。；;.]*?(?:三视图|设定图|色板|左右分栏)[^。；;.]*[。；;.]?")


def _strip_sheet_layout(prompt: str) -> str:
    """Drops the sheet-layout sentence a library/script jump-out seeds into
    the studio textarea (`characterSheetPrompt`), keeping the identity text."""
    return _SHEET_SENTENCE.sub("", prompt).strip(" ，,。")


def _compose_expressions(
    prompt: str, negative: str | None, expressions: list[str]
) -> tuple[str, str]:
    prompt = EXPRESSION_IDENTITY_PREFIX + _strip_sheet_layout(prompt)
    prompt = _join(prompt, expression_layout(expressions))
    prompt, negative_out = apply_visual_medium(prompt, negative)
    negative_out = merge_negative(negative_out, EXPRESSION_COMMON_NEGATIVE)
    if len(expressions) == 1:
        # Per-expression negatives contradict each other across cells (the
        # smile cell's 「假笑」 vs. the anger cell's 「微笑」), so only a single
        # close-up takes its own.
        negative_out = merge_negative(negative_out, EXPRESSION_PRESETS[expressions[0]].negative)
    return prompt, negative_out


def scene_preset_fragments(presets: dict[str, str]) -> tuple[str, str]:
    """`(prompt fragment, negative fragment)` for one preset combination."""
    sentences: list[str] = []
    negatives: list[str] = []
    for axis in SCENE_PRESET_AXES:
        key = presets.get(axis)
        if key is None:
            continue
        preset = SCENE_PRESET_TABLES[axis][key]
        sentences.append(preset.prompt)
        negatives.append(preset.negative)
        if axis == "period":
            period = PERIOD_PRESETS[key]
            sentences.append(f"年代线索：{'、'.join(period.cues)}")
            negatives.extend(period.pitfalls)
    return "；".join(sentences), "，".join(negatives)


def _compose_scene(
    prompt: str, negative: str | None, presets: dict[str, str], *, has_reference: bool
) -> tuple[str, str | None]:
    if not presets:
        return prompt, negative
    fragment, preset_negative = scene_preset_fragments(presets)
    if has_reference:
        prompt = SCENE_VARIANT_PREFIX.format(label=scene_preset_label(presets)) + prompt
    return _join(prompt, f"{fragment}。"), merge_negative(negative, preset_negative)


def compose_scene_group(
    prompt: str,
    negative: str | None,
    variants: list[dict[str, str]],
    *,
    has_reference: bool,
) -> tuple[str, str]:
    """One provider call, N separate scene images — one per variant, in order."""
    lines = []
    for index, variant in enumerate(variants, 1):
        fragment, _ = scene_preset_fragments(variant)
        lines.append(f"图{index}：{fragment}")
    head = (
        f"生成一组共 {len(variants)} 张独立的场景图，每张都是完整的单幅画面"
        "（不要拼接、分格或并排）。所有图片是同一场景、同一机位与构图、相同的建筑结构与陈设布局，"
        "仅以下条件不同——"
    )
    if has_reference:
        head = "以参考图1为基准，保持建筑结构、门窗位置、机位、透视与陈设布局完全一致。" + head
    composed = (
        f"{head}{'；'.join(lines)}。场景描述：{prompt}" if prompt else f"{head}{'；'.join(lines)}。"
    )
    return composed, merge_negative(negative, SCENE_GROUP_NEGATIVE)


def group_labels(params: dict[str, Any]) -> list[str]:
    """One write-back label per variant of a scene variant group, in order."""
    return [scene_preset_label(variant)[:60] for variant in _scene_variants(params)]


def _other_period_markers(period: str) -> list[str]:
    markers: list[str] = []
    for key, preset in PERIOD_PRESETS.items():
        if key != period:
            markers.append(preset.label)
    return markers


def sanitize_enhancements(
    asset_pass: AssetPass, items: Iterable[object], *, params: dict[str, Any]
) -> list[str]:
    """Drops planner additions that would contradict this pass.

    Enforced in Python on purpose: an operator-published `AgentSkill` can
    replace every rule the system prompt states, but not this.
    """
    kept: list[str] = []
    period = params.get("scene_period")
    foreign_periods = _other_period_markers(str(period)) if isinstance(period, str) else []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if asset_pass in (
            AssetPass.CHARACTER_EXPRESSIONS,
            AssetPass.SCENE,
            AssetPass.SCENE_VARIANT_GROUP,
        ) and any(marker in text for marker in _SHEET_MARKERS):
            continue
        if foreign_periods and any(marker in text for marker in foreign_periods):
            continue
        kept.append(text)
    return kept


# ---- reference legend ------------------------------------------------------

REFERENCE_LEGEND_PREFIX = "参考图说明："
GENERIC_REFERENCE_LABEL = "参考图"


def reference_legend(references: Iterable[Any], labels: dict[str, str], *, cap: int | None) -> str:
    """`参考图说明：图1 是…；图2 是…。` naming the images the provider receives.

    Only generic image references (no `frame_type`) are numbered, truncated
    to `cap` — adapters keep the front of the list — so a number never
    names an image the model doesn't get. Silent (`""`) when the cap is
    unknown, a first/last frame is present (positional frames, not a
    labelled set), fewer than two images survive, or no image has a
    meaningful label.
    """
    if cap is None or cap < 2:
        return ""
    refs = list(references)
    if any(getattr(ref, "frame_type", None) in ("first_frame", "last_frame") for ref in refs):
        return ""
    images = [
        ref
        for ref in refs
        if getattr(ref, "media_type", None) == "image" and getattr(ref, "frame_type", None) is None
    ][:cap]
    if len(images) < 2:
        return ""
    names = [
        labels.get(str(getattr(ref, "asset_id", "") or ""), GENERIC_REFERENCE_LABEL)
        for ref in images
    ]
    if all(name == GENERIC_REFERENCE_LABEL for name in names):
        return ""
    parts = "；".join(f"图{index} 是{name}" for index, name in enumerate(names, 1))
    return f"{REFERENCE_LEGEND_PREFIX}{parts}。请按以上对应关系使用各参考图。\n"


def strip_reference_legend(prompt: str) -> str:
    """Undoes `reference_legend` on a logged prompt (fast retry reads one back
    and must not end up with two legends)."""
    if prompt.startswith(REFERENCE_LEGEND_PREFIX) and "\n" in prompt:
        return prompt.split("\n", 1)[1]
    return prompt
