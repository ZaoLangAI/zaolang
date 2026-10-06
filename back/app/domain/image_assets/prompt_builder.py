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

from app.domain.image_assets import camera
from app.domain.image_assets.vocabulary import (
    EXPRESSION_PRESETS,
    PERIOD_PRESETS,
    SCENE_PRESET_AXES,
    SCENE_PRESET_TABLES,
    age_stage_fragments,
    character_period_fragments,
    expression_grid,
    prop_state_fragments,
    scene_preset_label,
    scene_presets_from,
)
from app.models.enums import CharacterViewAngle, ImageAssetKind


class AssetPass(StrEnum):
    """What one `asset_planning` pass is producing."""

    CHARACTER_SHEET = "character_sheet"
    IDENTITY_PORTRAIT = "identity_portrait"
    CHARACTER_COMPLETION = "character_completion"
    CHARACTER_EXPRESSIONS = "character_expressions"
    SCENE = "scene"
    # P6: redraw `source_entry_id` changing only what the prompt says.
    ASSET_EDIT = "asset_edit"
    # P6: the character from reference 1 placed in its look's linked scene.
    CHARACTER_IN_SCENE = "character_in_scene"
    # AC-2: reference 1 re-drawn from another camera pose (多机位).
    CAMERA_ORBIT = "camera_orbit"
    # AC-2: a sheet-sourced multi-angle job's first pass — the front single
    # figure drawn out of the sheet, which the other poses then orbit.
    SHEET_FRONT_FIGURE = "sheet_front_figure"
    # AC-4: a prop's hero plate (or a detail shot of it).
    PROP = "prop"
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

# The identity portrait (定妆照): the clean, single-face reference the anchor
# should be — the shape face-reference methods (Midjourney --cref/--oref,
# InstantID/PuLID) work best from. Head-and-shoulders, chosen 2026-10-02.
IDENTITY_PORTRAIT_LAYOUT = (
    "输出一张角色定妆照（单张画面，不要拆成多张）：单人、正面、头肩构图（取景到锁骨下方），"
    "双眼直视镜头、中性表情、嘴唇自然闭合；浅灰纯色背景，柔和均匀的正面光，面部无明显阴影；"
    "头发、饰品与手不遮挡五官与额头轮廓。"
)
IDENTITY_PORTRAIT_NEGATIVE = (
    "多人、多分格、拼接、三视图、设定图、色板、全身像、侧脸、背影、夸张表情、"
    "墨镜、口罩、遮挡面部、强烈阴影、复杂背景、文字、水印"
)
# A sheet / expression pass whose reference 1 is that portrait.
IDENTITY_LOCK_PREFIX = (
    "以参考图1（定妆照）中人物的面部为准，严格保持五官、发型发色、肤色与脸型完全一致；"
)

# A 换装 sheet with the character's existing sheet attached as reference 1.
# The prompt still carries the card's own description, which usually names
# the default look's clothes too (the library joins card + look text), so
# the prefix says outright which outfit wins.
OUTFIT_CHANGE_PREFIX = (
    "以参考图1中的人物为准，严格保持其五官、发型发色、肤色、体型与身高比例完全一致，"
    "仅将服装替换为「{label}」造型，角色描述里原有的服装与配饰一律不用："
)
OUTFIT_LABEL_SENTENCE = "本图为角色的「{label}」造型。"
# The target look's own outfit description (P2-3, `params["target_look"]`).
OUTFIT_DESCRIPTION_SENTENCE = "「{label}」造型的服装与配饰：{description}（以此替换角色原有服装）。"
LOOK_DESCRIPTION_SENTENCE = "服装与配饰：{description}。"


def _age_fragments(params: dict[str, Any]) -> tuple[str, str]:
    """The target look's age stage (P2-6) as `(prompt, negative)`."""
    raw = params.get("target_look")
    look: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return age_stage_fragments(look.get("age_stage"))


LOOK_STATE_SENTENCE = "人物状态：{state}。"
# A sheet stays on a white background; the scene is mood, not a backdrop.
LOOK_SCENE_NOTE_SENTENCE = "所处情境：{note}（只影响服装与状态，背景仍按版式要求）。"
LOOK_CUSTOM_SENTENCE = "其他设定：{items}。"


def _look_attribute_fragments(params: dict[str, Any]) -> tuple[str, str]:
    """The target look's period, state, scene note and custom attributes
    (P3) as `(prompt sentences, negative)`; empty when it has none."""
    raw = params.get("target_look")
    look: dict[str, Any] = raw if isinstance(raw, dict) else {}
    period, negative = character_period_fragments(look.get("period"))
    sentences = [period] if period else []
    state = str(look.get("state") or "").strip()
    if state:
        sentences.append(LOOK_STATE_SENTENCE.format(state=state))
    note = str(look.get("scene_note") or "").strip()
    if note:
        sentences.append(LOOK_SCENE_NOTE_SENTENCE.format(note=note))
    custom = [
        f"{item.get('key')}：{item.get('value')}"
        for item in look.get("custom") or []
        if isinstance(item, dict) and item.get("key") and item.get("value")
    ]
    if custom:
        sentences.append(LOOK_CUSTOM_SENTENCE.format(items="；".join(custom)))
    return "".join(sentences), negative


def _target_look(params: dict[str, Any]) -> tuple[str, str]:
    """`(outfit name, outfit description)` for a sheet pass: the job's
    `character_outfit_label`, else the target look's outfit attribute, else
    its name; the description only ever comes from the look
    (`reference_resolver` writes it)."""
    raw = params.get("target_look")
    look: dict[str, Any] = raw if isinstance(raw, dict) else {}
    name = str(
        params.get("character_outfit_label") or look.get("outfit") or look.get("name") or ""
    ).strip()
    description = str(look.get("description") or "").strip().rstrip("。．.")
    return name, description


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


def resolve_pass(
    params: dict[str, Any], *, asset_kind: str | None, character_view: str | None
) -> AssetPass:
    if params.get("orbit_front_extract") and asset_kind == ImageAssetKind.CHARACTER.value:
        return AssetPass.SHEET_FRONT_FIGURE
    if (
        camera.parse(params.get("camera_pose")) is not None
        and asset_kind in _ORBIT_KINDS
        and character_view not in CHARACTER_COMPLETION_FIXED_PROMPTS
    ):
        return AssetPass.CAMERA_ORBIT
    if params.get("asset_edit") and asset_kind in (
        ImageAssetKind.CHARACTER.value,
        ImageAssetKind.SCENE.value,
        ImageAssetKind.PROP.value,
    ):
        return AssetPass.ASSET_EDIT
    if asset_kind == ImageAssetKind.PROP.value:
        return AssetPass.PROP
    if (
        asset_kind == ImageAssetKind.CHARACTER.value
        and params.get("asset_output_mode") == "in_scene"
    ):
        return AssetPass.CHARACTER_IN_SCENE
    if asset_kind == ImageAssetKind.CHARACTER.value:
        if character_view in CHARACTER_COMPLETION_FIXED_PROMPTS:
            return AssetPass.CHARACTER_COMPLETION
        if _expressions(params):
            return AssetPass.CHARACTER_EXPRESSIONS
        if params.get("character_portrait"):
            return AssetPass.IDENTITY_PORTRAIT
        return AssetPass.CHARACTER_SHEET
    if asset_kind == ImageAssetKind.SCENE.value:
        # A scene variant set runs one SCENE pass per variant, with that
        # variant's presets already folded into the params
        # (`nodes._pass_params`).
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
    identity_reference: bool = False,
) -> tuple[str, str | None]:
    """The pass's prompt and negative prompt before the planner adds to them.

    `identity_reference`: reference 1 is the card's approved identity
    portrait, so a sheet pass locks the face to it (`IDENTITY_LOCK_PREFIX`).
    """
    if asset_pass is AssetPass.CHARACTER_COMPLETION and character_view:
        return (
            CHARACTER_COMPLETION_FIXED_PROMPTS[character_view],
            merge_negative(negative, CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT),
        )
    if asset_pass is AssetPass.CAMERA_ORBIT:
        return _compose_camera_orbit(prompt, negative, params)
    if asset_pass is AssetPass.SHEET_FRONT_FIGURE:
        subject = _strip_sheet_layout(prompt).strip().rstrip("。．.")
        text = (
            _join(SHEET_FRONT_FIGURE_PROMPT, f"主体：{subject}")
            if subject
            else (SHEET_FRONT_FIGURE_PROMPT)
        )
        return text, merge_negative(negative, SHEET_FRONT_FIGURE_NEGATIVE)
    if asset_pass is AssetPass.ASSET_EDIT:
        return (
            ASSET_EDIT_TEMPLATE.format(instruction=prompt.strip().rstrip("。．.")),
            merge_negative(negative, ASSET_EDIT_NEGATIVE),
        )
    if asset_pass is AssetPass.CHARACTER_IN_SCENE:
        return _compose_character_in_scene(prompt, negative, params)
    if asset_pass is AssetPass.IDENTITY_PORTRAIT:
        return _compose_identity_portrait(prompt, negative, has_reference=has_reference)
    if asset_pass is AssetPass.CHARACTER_SHEET:
        return _compose_character_sheet(
            prompt,
            negative,
            params,
            has_reference=has_reference,
            identity_reference=identity_reference,
        )
    if asset_pass is AssetPass.CHARACTER_EXPRESSIONS:
        prompt_out, negative_out = _compose_expressions(prompt, negative, _expressions(params))
        for fragment, fragment_negative in (
            _age_fragments(params),
            _look_attribute_fragments(params),
        ):
            if fragment:
                prompt_out = _join(prompt_out, fragment)
                negative_out = merge_negative(negative_out, fragment_negative)
        return prompt_out, negative_out
    if asset_pass is AssetPass.PROP:
        return _compose_prop(prompt, negative, params, has_reference=has_reference)
    if asset_pass is AssetPass.SCENE:
        return _compose_scene(
            prompt, negative, scene_presets_from(params), has_reference=has_reference
        )
    return prompt, negative


# 多机位 (AC-2): reference 1 is the subject; only the camera moves. The move
# is spelled out in words too (`camera.to_prompt_phrase`) so a model without
# camera control (the fallback route) still gets it; the fal camera route
# reads the pose from `extra.camera_pose` and this text as its extra prompt.
_ORBIT_KINDS = frozenset({ImageAssetKind.CHARACTER.value, ImageAssetKind.SCENE.value, "prop"})
CAMERA_ORBIT_LOCKS: dict[str, str] = {
    ImageAssetKind.CHARACTER.value: (
        "以参考图1中的人物为准，严格保持五官、发型发色、肤色、体型、服装配饰与画风完全一致，"
        "只改变拍摄机位：{phrase}。单张单人画面，纯色背景，全身不裁切头脚"
    ),
    ImageAssetKind.SCENE.value: (
        "以参考图1中的场景为准，保持建筑结构、陈设布局、材质、光线与时间完全一致，"
        "只改变拍摄机位：{phrase}。单张画面，画面中不出现人物"
    ),
    "prop": (
        "以参考图1中的物体为准，保持形状、比例、材质、颜色与磨损细节完全一致，"
        "只改变拍摄机位：{phrase}。单张画面，主体完整居中，纯色背景"
    ),
}
SHEET_FRONT_FIGURE_PROMPT = (
    "从参考图1（角色设定图）中取出该角色的正面全身形象：单人、正面、全身站姿、不裁切头脚、"
    "纯白背景，严格保持五官、发型发色、服装配饰、体型与画风完全一致"
)
SHEET_FRONT_FIGURE_NEGATIVE = (
    "三视图、多个相同人物、面部特写分格、色板、文字标注、侧面、背面、改变服装"
)
CAMERA_ORBIT_NEGATIVE = (
    "多视角拼接、分格、并排画面、三视图、同一画面出现多个相同主体、视角文字标注、"
    "改变服装或材质、改变配色"
)


def _compose_camera_orbit(
    prompt: str, negative: str | None, params: dict[str, Any]
) -> tuple[str, str]:
    pose = camera.parse(params.get("camera_pose"))
    phrase = camera.to_prompt_phrase(pose) if pose is not None else ""
    kind = str(params.get("asset_kind") or ImageAssetKind.CHARACTER.value)
    lock = CAMERA_ORBIT_LOCKS.get(kind, CAMERA_ORBIT_LOCKS["prop"]).format(phrase=phrase)
    subject = _strip_sheet_layout(prompt).strip().rstrip("。．.")
    text = _join(lock, f"主体：{subject}") if subject else lock
    return text, merge_negative(negative, CAMERA_ORBIT_NEGATIVE)


# 道具 (AC-4): a hero plate reads like a product shot — the whole object,
# nothing else in frame — so it can be re-used as a reference anywhere.
PROP_HERO_LAYOUT = (
    "输出一张道具主视图（单张画面）：物体完整居中、不裁切，三分之四正面角度，"
    "浅灰纯色背景，柔和均匀的棚拍光，可见材质与细节；画面中只有这一件物体"
)
PROP_DETAIL_LAYOUT = "输出一张道具局部特写：聚焦材质、纹理与标志性细节，浅灰纯色背景，单张画面"
PROP_REFERENCE_PREFIX = "以参考图1中的物体为准，保持形状、比例、材质与颜色完全一致；"
PROP_NEGATIVE = "人物，手，多个物体，杂乱背景，文字，水印，拼贴分格"


def _compose_prop(
    prompt: str, negative: str | None, params: dict[str, Any], *, has_reference: bool
) -> tuple[str, str]:
    detail = params.get("asset_output_entry_type") == "shot"
    text = (PROP_REFERENCE_PREFIX + prompt) if has_reference else prompt
    state, state_negative = prop_state_fragments(params.get("prop_state"))
    if state:
        text = _join(text, state.rstrip("。"))
    text = _join(text, PROP_DETAIL_LAYOUT if detail else PROP_HERO_LAYOUT)
    negative_out = merge_negative(negative, PROP_NEGATIVE)
    return text, merge_negative(negative_out, state_negative)


# 调整修改 (P6): the instruction is the whole intent; everything it does not
# name stays as reference 1 has it — including a sheet's own layout.
ASSET_EDIT_TEMPLATE = (
    "以参考图1为基础，只做以下修改：{instruction}。"
    "未提及的部分（人物身份与五官、服装、构图与版式、背景与光线）保持与参考图1完全一致。"
)
ASSET_EDIT_NEGATIVE = "换成另一个人，构图改变，版式改变，新增无关元素"
# 角色入场景 (P6): reference 1 is the character, the last reference the
# linked scene (`reference_resolver.SCENE_ONLY_ROLE`).
IN_SCENE_PREFIX = "以参考图1中的人物为准，严格保持五官、发型发色、肤色、体型与服装完全一致；"
IN_SCENE_LAYOUT = (
    "将人物自然地置于参考图中场景的环境与光线里（只取场景，不要照搬场景图里的其他人物），"
    "单张画面，全身或中景构图，人物与环境的透视、光影一致"
)
IN_SCENE_NEGATIVE = "设定图版式，三视图，分格拼贴，色板，多个相同人物，纯白背景"


def _compose_character_in_scene(
    prompt: str, negative: str | None, params: dict[str, Any]
) -> tuple[str, str]:
    prompt = IN_SCENE_PREFIX + _strip_sheet_layout(prompt)
    for fragment, _ in (_age_fragments(params), _look_attribute_fragments(params)):
        if fragment and fragment not in prompt:
            prompt = _join(prompt, fragment)
    prompt = _join(prompt, IN_SCENE_LAYOUT)
    prompt, negative_out = apply_visual_medium(prompt, negative)
    age_negative = _age_fragments(params)[1]
    attributes_negative = _look_attribute_fragments(params)[1]
    for extra in (IN_SCENE_NEGATIVE, age_negative, attributes_negative):
        negative_out = merge_negative(negative_out, extra)
    return prompt, negative_out


def _compose_identity_portrait(
    prompt: str, negative: str | None, *, has_reference: bool
) -> tuple[str, str]:
    """Keeps the caller's identity text, drops any sheet-layout sentence a
    library jump-out seeded, and asks for one clean head-and-shoulders face."""
    prompt = _strip_sheet_layout(prompt)
    if has_reference:
        prompt = EXPRESSION_IDENTITY_PREFIX + prompt
    prompt = _join(prompt, IDENTITY_PORTRAIT_LAYOUT)
    prompt, negative_out = apply_visual_medium(prompt, negative)
    return prompt, merge_negative(negative_out, IDENTITY_PORTRAIT_NEGATIVE)


def _compose_character_sheet(
    prompt: str,
    negative: str | None,
    params: dict[str, Any],
    *,
    has_reference: bool,
    identity_reference: bool = False,
) -> tuple[str, str]:
    outfit, description = _target_look(params)
    if outfit and has_reference:
        # 换装 already locks the face to reference 1 — one sentence, not two.
        prompt = OUTFIT_CHANGE_PREFIX.format(label=outfit) + prompt
    elif outfit:
        prompt = _join(prompt, OUTFIT_LABEL_SENTENCE.format(label=outfit))
    if description:
        sentence = (
            OUTFIT_DESCRIPTION_SENTENCE.format(label=outfit, description=description)
            if outfit
            else LOOK_DESCRIPTION_SENTENCE.format(description=description)
        )
        if description not in prompt:
            prompt = _join(prompt, sentence)
    if identity_reference and not (outfit and has_reference):
        prompt = IDENTITY_LOCK_PREFIX + prompt
    age, age_negative = _age_fragments(params)
    if age and age not in prompt:
        prompt = _join(prompt, age)
    attributes, attributes_negative = _look_attribute_fragments(params)
    if attributes and attributes not in prompt:
        prompt = _join(prompt, attributes)
    if CHARACTER_SHEET_LAYOUT_SUFFIX not in prompt:
        prompt = _join(prompt, CHARACTER_SHEET_LAYOUT_SUFFIX)
    prompt, negative_out = apply_visual_medium(prompt, negative)
    negative_out = merge_negative(negative_out, age_negative)
    return prompt, merge_negative(negative_out, attributes_negative)


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
    if asset_pass in (AssetPass.ASSET_EDIT, AssetPass.CAMERA_ORBIT, AssetPass.SHEET_FRONT_FIGURE):
        # An edit does exactly what the author asked, and a camera move must
        # keep everything but the camera; planner additions would be
        # unrequested changes.
        return []
    kept: list[str] = []
    period = params.get("scene_period")
    foreign_periods = _other_period_markers(str(period)) if isinstance(period, str) else []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        sheetless = (
            AssetPass.CHARACTER_EXPRESSIONS,
            AssetPass.IDENTITY_PORTRAIT,
            AssetPass.SCENE,
            AssetPass.CHARACTER_IN_SCENE,
        )
        if asset_pass in sheetless and any(marker in text for marker in _SHEET_MARKERS):
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
