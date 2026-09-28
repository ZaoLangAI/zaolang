"""Validated EditCommand batches. Manual UI, AI and MCP share this contract."""

from __future__ import annotations

from typing import Any

from app.domain.editor import document as docs
from app.domain.editor.time import MAX_COMMANDS_PER_BATCH, MAX_TRACKS_PER_KIND, assert_safe_ticks
from app.domain.errors import BatchRolledBack, ValidationFailed
from app.models.base import new_id

# Tracks a clip/caption can actually be inserted onto. `trk_caption`/
# `trk_overlay`-kind tracks are permanent singletons managed separately.
TRACK_KINDS_ADDABLE = frozenset({"video", "audio"})

# `blur` alone runs on the vendored WASM module's real `gaussian-blur`
# shader (confirmed the only one actually registered in the pinned Rust
# pipeline by direct empirical test); the rest are always a Canvas2D
# `ctx.filter` on the frontend. Kept closed here so a caller can never
# request an effect the renderer has no path for at all.
EFFECT_TYPES = frozenset({"blur", "brightness", "contrast", "saturate", "grayscale"})
MASK_SHAPES = frozenset({"rect", "ellipse"})
MAX_EFFECTS_PER_ELEMENT = 8

# A closed, per-property-validated enum — not the generic path/value update
# `validate_batch` permanently forbids (see the guard a few lines down).
# `set_keyframe`'s `property` field only ever selects one of these five
# names, each with its own numeric range; it can never address an
# arbitrary tree path into the document.
ANIMATABLE_PROPERTIES = frozenset(
    {
        "opacity",
        "transform.x_milli",
        "transform.y_milli",
        "transform.scale_millipercent",
        "transform.rotation_millidegrees",
        "volume",
    }
)
PROPERTY_RANGES: dict[str, tuple[int, int]] = {
    "opacity": (0, 100_000),
    "transform.x_milli": (-2000, 2000),
    "transform.y_milli": (-2000, 2000),
    "transform.scale_millipercent": (10_000, 500_000),
    "transform.rotation_millidegrees": (-180_000, 180_000),
    # Same millipercent range `set_clip_volume` already accepts — a `volume`
    # keyframe channel is an alternative, time-varying way to drive the same
    # underlying value, not a separate concept with its own scale.
    "volume": (0, 200_000),
}
MAX_KEYFRAMES_PER_CHANNEL = 64

# Attached to a keyframe point to shape the curve used when interpolating
# *away from* that point towards the next one (see `animation.ts`'s
# `resolveNumberAtTime`). Closed for the same reason `ANIMATABLE_PROPERTIES`
# is: a fixed, tested set of curves, not an open-ended expression language.
EASING_TYPES = frozenset({"linear", "ease_in", "ease_out"})
DEFAULT_EASING = "linear"

MAX_MARKERS = 200

# 'sticker' is structurally identical to the default 'clip' — same fields,
# same track kind, just a different visual role.
ELEMENT_TYPES_ADDABLE = frozenset({"clip", "sticker"})
TRANSITION_TYPES = frozenset({"crossfade", "dip_to_black"})

ALLOWED_TYPES = frozenset(
    {
        "insert_clip",
        "delete_elements",
        "move_elements",
        "duplicate_elements",
        "trim_element",
        "split_element",
        "set_clip_volume",
        "set_clip_speed",
        "insert_caption",
        "update_caption",
        "set_canvas",
        "set_brand_overlay",
        "add_track",
        "remove_track",
        "set_track_order",
        "set_track_muted",
        "add_effect",
        "remove_effect",
        "update_effect_params",
        "set_clip_mask",
        "set_keyframe",
        "delete_keyframe",
        "clear_keyframes",
        "set_transition",
        "add_marker",
        "remove_marker",
        "update_marker",
    }
)


def validate_batch(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationFailed("命令批次必须是对象。")
    extra = set(payload) - {"schema_version", "batch_id", "expected_revision_id", "commands"}
    if extra:
        raise ValidationFailed("命令批次含有未知字段。", fields={"unknown": sorted(extra)})
    if int(payload.get("schema_version") or 0) != 1:
        raise ValidationFailed("不支持的命令 schema。")
    batch_id = str(payload.get("batch_id") or "").strip()
    if not batch_id:
        raise ValidationFailed("缺少 batch_id。")
    commands = payload.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValidationFailed("commands 不能为空。")
    if len(commands) > MAX_COMMANDS_PER_BATCH:
        raise ValidationFailed(f"单批最多 {MAX_COMMANDS_PER_BATCH} 条命令。")
    normalised: list[dict[str, Any]] = []
    for index, raw in enumerate(commands):
        if not isinstance(raw, dict):
            raise ValidationFailed(f"commands[{index}] 必须是对象。")
        command_type = raw.get("type")
        if command_type not in ALLOWED_TYPES:
            raise ValidationFailed(f"不支持的命令类型: {command_type}。")
        if "path" in raw or command_type == "update_property":
            raise ValidationFailed("禁止通用路径更新。")
        extra_keys = set(raw) - _allowed_keys(str(command_type))
        if extra_keys:
            raise ValidationFailed(
                f"commands[{index}] 含有未知字段。", fields={"unknown": sorted(extra_keys)}
            )
        _validate_command(raw)
        normalised.append(raw)
    expected = payload.get("expected_revision_id")
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "expected_revision_id": str(expected) if expected else None,
        "commands": normalised,
    }


def apply_batch(
    document: dict[str, Any],
    commands: list[dict[str, Any]],
    *,
    known_assets: set[str] | None = None,
) -> dict[str, Any]:
    working = docs.clone_document(document)
    applied: list[dict[str, Any]] = []
    try:
        for command in commands:
            _apply_one(working, command, known_assets=known_assets or set())
            applied.append(command)
        docs.validate_document(working)
    except Exception as exc:
        raise BatchRolledBack("命令批次已回滚，未改动时间线。", reason=str(exc)) from exc
    return working


def _allowed_keys(command_type: str) -> set[str]:
    common = {"type"}
    mapping: dict[str, set[str]] = {
        "insert_clip": {
            "track_id",
            "asset_id",
            "at_ticks",
            "duration_ticks",
            "source_in_ticks",
            "element_id",
            "element_type",
        },
        "delete_elements": {"element_ids"},
        "move_elements": {"element_ids", "delta_ticks", "track_id"},
        "duplicate_elements": {"element_ids", "delta_ticks", "new_element_ids"},
        "trim_element": {
            "element_id",
            "start_ticks",
            "duration_ticks",
            "source_in_ticks",
            "source_out_ticks",
        },
        "split_element": {"element_id", "at_ticks", "new_element_id"},
        "set_clip_volume": {"element_id", "volume_millipercent"},
        "set_clip_speed": {"element_id", "speed_millipercent"},
        "insert_caption": {
            "track_id",
            "at_ticks",
            "duration_ticks",
            "text",
            "caption_language",
            "element_id",
        },
        "update_caption": {"element_id", "text", "at_ticks", "duration_ticks"},
        "set_canvas": {"width", "height", "fps_num", "fps_den"},
        "set_brand_overlay": {"overlay"},
        "add_track": {"kind", "label", "order", "track_id"},
        "remove_track": {"track_id"},
        "set_track_order": {"track_id", "order"},
        "set_track_muted": {"track_id", "muted"},
        "add_effect": {"element_id", "effect"},
        "remove_effect": {"element_id", "effect_index"},
        "update_effect_params": {"element_id", "effect_index", "params"},
        "set_clip_mask": {"element_id", "mask"},
        "set_keyframe": {"element_id", "property", "at_ticks", "value", "easing"},
        "delete_keyframe": {"element_id", "property", "at_ticks"},
        "clear_keyframes": {"element_id", "property"},
        "set_transition": {"element_id", "edge", "transition"},
        "add_marker": {"at_ticks", "label", "marker_id"},
        "remove_marker": {"marker_id"},
        "update_marker": {"marker_id", "at_ticks", "label"},
    }
    return common | mapping[command_type]


def _require_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationFailed(f"{label} 必须是整数 tick。")
    try:
        return assert_safe_ticks(value, label=label)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


def _validate_command(command: dict[str, Any]) -> None:
    command_type = command["type"]
    if command_type in {"insert_clip", "insert_caption", "split_element"} and "at_ticks" in command:
        _require_int(command["at_ticks"], label="at_ticks")
    if "duration_ticks" in command and command["duration_ticks"] is not None:
        duration = _require_int(command["duration_ticks"], label="duration_ticks")
        if duration <= 0:
            raise ValidationFailed("duration_ticks 必须为正。")
    if command_type == "set_clip_volume":
        volume = int(command["volume_millipercent"])
        if volume < 0 or volume > 200_000:
            raise ValidationFailed("音量 millipercent 必须在 0 到 200000 之间。")
    if command_type == "set_clip_speed":
        speed = int(command["speed_millipercent"])
        if speed < 25_000 or speed > 400_000:
            raise ValidationFailed("倍速 millipercent 必须在 25000 到 400000 之间。")
    if command_type in {"delete_elements", "duplicate_elements"}:
        ids = command.get("element_ids")
        if not isinstance(ids, list) or not ids:
            raise ValidationFailed("element_ids 不能为空。")
    if command_type == "duplicate_elements" and command.get("delta_ticks") is not None:
        delta = command["delta_ticks"]
        # Negative is fine here (paste before the source), so this deliberately
        # isn't `_require_int`, which rejects anything below zero.
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise ValidationFailed("delta_ticks 必须是整数 tick。")
    if command_type == "duplicate_elements" and command.get("new_element_ids") is not None:
        new_ids = command["new_element_ids"]
        if (
            not isinstance(new_ids, list)
            or len(new_ids) != len(command.get("element_ids") or [])
            or any(not isinstance(item, str) or not item.strip() for item in new_ids)
            or len(set(new_ids)) != len(new_ids)
        ):
            raise ValidationFailed("new_element_ids 必须与 element_ids 一一对应且互不重复。")
    if command_type == "split_element" and command.get("new_element_id") is not None:
        new_id_value = command["new_element_id"]
        if not isinstance(new_id_value, str) or not new_id_value.strip():
            raise ValidationFailed("new_element_id 必须是非空字符串。")
    if command_type == "insert_clip" and not command.get("asset_id"):
        raise ValidationFailed("insert_clip 需要 asset_id。")
    if command_type == "insert_caption" and not str(command.get("text") or "").strip():
        raise ValidationFailed("字幕不能为空。")
    if command_type == "add_track" and command.get("kind") not in TRACK_KINDS_ADDABLE:
        raise ValidationFailed("轨道类型必须是 video 或 audio。")
    if command_type == "add_effect":
        effect = command.get("effect")
        if not isinstance(effect, dict) or effect.get("type") not in EFFECT_TYPES:
            raise ValidationFailed("不支持的特效类型。")
        if not isinstance(effect.get("params"), dict):
            raise ValidationFailed("特效参数必须是对象。")
    if command_type in {"remove_effect", "update_effect_params"}:
        index = command.get("effect_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValidationFailed("特效索引必须是非负整数。")
    if command_type == "update_effect_params" and not isinstance(command.get("params"), dict):
        raise ValidationFailed("特效参数必须是对象。")
    if command_type == "set_clip_mask":
        mask = command.get("mask")
        if mask is not None and (
            not isinstance(mask, dict) or mask.get("shape") not in MASK_SHAPES
        ):
            raise ValidationFailed("不支持的蒙版形状。")
    if (
        command_type in {"set_keyframe", "delete_keyframe", "clear_keyframes"}
        and command.get("property") not in ANIMATABLE_PROPERTIES
    ):
        raise ValidationFailed("不支持的动画属性。")
    if command_type in {"set_keyframe", "delete_keyframe"}:
        _require_int(command["at_ticks"], label="at_ticks")
    if command_type == "set_keyframe":
        value = command.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationFailed("关键帧的值必须是整数。")
        low, high = PROPERTY_RANGES[command["property"]]
        if value < low or value > high:
            raise ValidationFailed(f"{command['property']} 的值必须在 {low} 到 {high} 之间。")
        easing = command.get("easing")
        if easing is not None and easing not in EASING_TYPES:
            raise ValidationFailed("不支持的缓动类型。")
    if command_type == "add_marker":
        _require_int(command["at_ticks"], label="at_ticks")
        label = command.get("label")
        if label is not None and len(str(label)) > 120:
            raise ValidationFailed("标记点文案最多 120 字符。")
    if command_type == "update_marker":
        if "at_ticks" in command and command["at_ticks"] is not None:
            _require_int(command["at_ticks"], label="at_ticks")
        label = command.get("label")
        if label is not None and len(str(label)) > 120:
            raise ValidationFailed("标记点文案最多 120 字符。")
    if (
        command_type == "insert_clip"
        and "element_type" in command
        and command["element_type"] is not None
        and command["element_type"] not in ELEMENT_TYPES_ADDABLE
    ):
        raise ValidationFailed("不支持的元素类型。")
    if command_type == "set_transition":
        if command.get("edge") not in {"in", "out"}:
            raise ValidationFailed("edge 必须是 in 或 out。")
        transition = command.get("transition")
        if transition is not None:
            if not isinstance(transition, dict) or transition.get("type") not in TRANSITION_TYPES:
                raise ValidationFailed("不支持的转场类型。")
            transition_ticks = transition.get("duration_ticks")
            if (
                not isinstance(transition_ticks, int)
                or isinstance(transition_ticks, bool)
                or transition_ticks <= 0
            ):
                raise ValidationFailed("转场时长必须为正整数 tick。")


def _apply_one(
    document: dict[str, Any], command: dict[str, Any], *, known_assets: set[str]
) -> None:
    command_type = command["type"]
    if command_type == "insert_clip":
        _insert_clip(document, command, known_assets=known_assets)
    elif command_type == "delete_elements":
        ids = set(command["element_ids"])
        for track in document["tracks"]:
            track["elements"] = [el for el in track["elements"] if el["id"] not in ids]
    elif command_type == "move_elements":
        _move_elements(document, command)
    elif command_type == "duplicate_elements":
        _duplicate_elements(document, command)
    elif command_type == "trim_element":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        _, element = found
        element["start_ticks"] = int(command["start_ticks"])
        element["duration_ticks"] = int(command["duration_ticks"])
        element["source_in_ticks"] = int(command["source_in_ticks"])
        element["source_out_ticks"] = int(command["source_out_ticks"])
    elif command_type == "split_element":
        _split_element(document, command)
    elif command_type == "set_clip_volume":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        found[1]["volume_millipercent"] = int(command["volume_millipercent"])
    elif command_type == "set_clip_speed":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        found[1]["speed_millipercent"] = int(command["speed_millipercent"])
    elif command_type == "insert_caption":
        _insert_caption(document, command)
    elif command_type == "update_caption":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        element = found[1]
        if element.get("type") != "caption":
            raise ValidationFailed("目标不是字幕。")
        if "text" in command and command["text"] is not None:
            element["text"] = str(command["text"])
        if "at_ticks" in command and command["at_ticks"] is not None:
            element["start_ticks"] = int(command["at_ticks"])
        if "duration_ticks" in command and command["duration_ticks"] is not None:
            element["duration_ticks"] = int(command["duration_ticks"])
    elif command_type == "set_canvas":
        canvas = document.setdefault("canvas", {})
        canvas["width"] = int(command["width"])
        canvas["height"] = int(command["height"])
        if command.get("fps_num"):
            canvas["fps_num"] = int(command["fps_num"])
        if command.get("fps_den"):
            canvas["fps_den"] = int(command["fps_den"])
    elif command_type == "set_brand_overlay":
        overlay = command.get("overlay")
        if overlay is None:
            document["brand_overlay"] = None
            return
        asset_id = str(overlay.get("asset_id") or "")
        if known_assets and asset_id not in known_assets:
            raise ValidationFailed("品牌素材不存在或不属于该项目。")
        document["brand_overlay"] = {
            "asset_id": asset_id,
            "x_milli": int(overlay.get("x_milli") or 0),
            "y_milli": int(overlay.get("y_milli") or 0),
            "width_milli": int(overlay.get("width_milli") or 200),
        }
    elif command_type == "add_track":
        _add_track(document, command)
    elif command_type == "remove_track":
        _remove_track(document, command)
    elif command_type == "set_track_order":
        track = docs.find_track(document, command["track_id"])
        if track is None:
            raise ValidationFailed("轨道不存在。")
        track["order"] = int(command["order"])
    elif command_type == "set_track_muted":
        track = docs.find_track(document, command["track_id"])
        if track is None:
            raise ValidationFailed("轨道不存在。")
        track["muted"] = bool(command["muted"])
    elif command_type == "add_effect":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        effect = command["effect"]
        if effect.get("type") not in EFFECT_TYPES:
            raise ValidationFailed("不支持的特效类型。")
        element = found[1]
        effects = element.setdefault("effects", [])
        if len(effects) >= MAX_EFFECTS_PER_ELEMENT:
            raise ValidationFailed(f"单个元素最多 {MAX_EFFECTS_PER_ELEMENT} 个特效。")
        effects.append({"type": effect["type"], "params": dict(effect.get("params") or {})})
    elif command_type == "remove_effect":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        effects = found[1].setdefault("effects", [])
        index = int(command["effect_index"])
        if index < 0 or index >= len(effects):
            raise ValidationFailed("特效索引越界。")
        del effects[index]
    elif command_type == "update_effect_params":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        effects = found[1].setdefault("effects", [])
        index = int(command["effect_index"])
        if index < 0 or index >= len(effects):
            raise ValidationFailed("特效索引越界。")
        effects[index]["params"] = {**effects[index].get("params", {}), **command["params"]}
    elif command_type == "set_clip_mask":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        mask = command.get("mask")
        if mask is None:
            found[1]["mask"] = None
        else:
            if mask.get("shape") not in MASK_SHAPES:
                raise ValidationFailed("不支持的蒙版形状。")
            found[1]["mask"] = {
                "shape": mask["shape"],
                "x_milli": int(mask.get("x_milli") or 0),
                "y_milli": int(mask.get("y_milli") or 0),
                "width_milli": int(mask.get("width_milli") or 0),
                "height_milli": int(mask.get("height_milli") or 0),
                "feather_millipercent": int(mask.get("feather_millipercent") or 0),
            }
    elif command_type == "set_keyframe":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        prop = command["property"]
        if prop not in ANIMATABLE_PROPERTIES:
            raise ValidationFailed("不支持的动画属性。")
        low, high = PROPERTY_RANGES[prop]
        value = int(command["value"])
        if value < low or value > high:
            raise ValidationFailed(f"{prop} 的值必须在 {low} 到 {high} 之间。")
        at_ticks = int(command["at_ticks"])
        easing = command.get("easing") or DEFAULT_EASING
        if easing not in EASING_TYPES:
            raise ValidationFailed("不支持的缓动类型。")
        animations = found[1].setdefault("animations", {"channels": {}})
        channels = animations.setdefault("channels", {})
        existing = channels.get(prop)
        points = [
            p for p in (existing.get("points") if existing else []) if p["at_ticks"] != at_ticks
        ]
        if len(points) >= MAX_KEYFRAMES_PER_CHANNEL:
            raise ValidationFailed(f"单个属性最多 {MAX_KEYFRAMES_PER_CHANNEL} 个关键帧。")
        points.append({"at_ticks": at_ticks, "value": value, "easing": easing})
        points.sort(key=lambda p: p["at_ticks"])
        channels[prop] = {"kind": "number", "points": points}
    elif command_type == "delete_keyframe":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        prop = command["property"]
        if prop not in ANIMATABLE_PROPERTIES:
            raise ValidationFailed("不支持的动画属性。")
        at_ticks = int(command["at_ticks"])
        animations = found[1].setdefault("animations", {"channels": {}})
        channels = animations.setdefault("channels", {})
        existing = channels.get(prop)
        points = existing.get("points") if existing else []
        next_points = [p for p in points if p["at_ticks"] != at_ticks]
        if len(next_points) == len(points):
            raise ValidationFailed("该时间点没有关键帧。")
        channels[prop] = {"kind": "number", "points": next_points}
    elif command_type == "clear_keyframes":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        prop = command["property"]
        if prop not in ANIMATABLE_PROPERTIES:
            raise ValidationFailed("不支持的动画属性。")
        channels = found[1].setdefault("animations", {"channels": {}}).setdefault("channels", {})
        channels.pop(prop, None)
    elif command_type == "set_transition":
        found = docs.find_element(document, command["element_id"])
        if found is None:
            raise ValidationFailed("元素不存在。")
        edge = command["edge"]
        if edge not in {"in", "out"}:
            raise ValidationFailed("edge 必须是 in 或 out。")
        transition = command.get("transition")
        if transition is not None:
            if transition.get("type") not in TRANSITION_TYPES:
                raise ValidationFailed("不支持的转场类型。")
            duration = int(transition["duration_ticks"])
            if duration <= 0 or duration > int(found[1]["duration_ticks"]):
                raise ValidationFailed("转场时长必须大于零且不超过该元素自身时长。")
            transition = {"type": transition["type"], "duration_ticks": duration}
        found[1][f"transition_{edge}"] = transition
    elif command_type == "add_marker":
        markers = document.setdefault("markers", [])
        if len(markers) >= MAX_MARKERS:
            raise ValidationFailed(f"最多 {MAX_MARKERS} 个标记点。")
        marker_id = command.get("marker_id") or new_id("mrk")
        if any(m["id"] == marker_id for m in markers):
            raise ValidationFailed("标记点 id 已存在。")
        markers.append(
            {
                "id": marker_id,
                "at_ticks": int(command["at_ticks"]),
                "label": command.get("label"),
            }
        )
    elif command_type == "remove_marker":
        markers = document.setdefault("markers", [])
        next_markers = [m for m in markers if m["id"] != command["marker_id"]]
        if len(next_markers) == len(markers):
            raise ValidationFailed("标记点不存在。")
        document["markers"] = next_markers
    elif command_type == "update_marker":
        markers = document.setdefault("markers", [])
        marker = next((m for m in markers if m["id"] == command["marker_id"]), None)
        if marker is None:
            raise ValidationFailed("标记点不存在。")
        if "at_ticks" in command and command["at_ticks"] is not None:
            marker["at_ticks"] = int(command["at_ticks"])
        if "label" in command:
            marker["label"] = command["label"]


def _add_track(document: dict[str, Any], command: dict[str, Any]) -> None:
    kind = command["kind"]
    if kind not in TRACK_KINDS_ADDABLE:
        raise ValidationFailed("轨道类型必须是 video 或 audio。")
    same_kind = [t for t in document["tracks"] if t.get("kind") == kind]
    if len(same_kind) >= MAX_TRACKS_PER_KIND:
        raise ValidationFailed(f"同类轨道最多 {MAX_TRACKS_PER_KIND} 条。")
    track_id = command.get("track_id") or new_id("trk")
    if docs.find_track(document, track_id) is not None:
        raise ValidationFailed("轨道 id 已存在。")
    max_order = max((int(t.get("order") or 0) for t in same_kind), default=-1)
    order = command.get("order")
    document["tracks"].append(
        {
            "id": track_id,
            "kind": kind,
            "elements": [],
            "order": int(order) if order is not None else max_order + 1,
            "label": command.get("label"),
            "muted": False,
        }
    )


def _remove_track(document: dict[str, Any], command: dict[str, Any]) -> None:
    track = docs.find_track(document, command["track_id"])
    if track is None:
        raise ValidationFailed("轨道不存在。")
    if track.get("kind") not in TRACK_KINDS_ADDABLE:
        raise ValidationFailed("字幕轨与角标轨不可删除。")
    if track.get("elements"):
        raise ValidationFailed("轨道非空，无法删除，请先移除轨道上的元素。")
    remaining = [t for t in document["tracks"] if t.get("kind") == track.get("kind")]
    if len(remaining) <= 1:
        raise ValidationFailed("至少保留一条该类型轨道。")
    document["tracks"] = [t for t in document["tracks"] if t.get("id") != track["id"]]


def _insert_clip(
    document: dict[str, Any], command: dict[str, Any], *, known_assets: set[str]
) -> None:
    track = docs.find_track(document, command["track_id"])
    if track is None:
        raise ValidationFailed("轨道不存在。")
    if track.get("kind") not in TRACK_KINDS_ADDABLE:
        raise ValidationFailed("片段只能插入视频或音频轨道。")
    element_type = command.get("element_type") or "clip"
    if element_type not in ELEMENT_TYPES_ADDABLE:
        raise ValidationFailed("不支持的元素类型。")
    asset_id = str(command["asset_id"])
    if known_assets and asset_id not in known_assets:
        raise ValidationFailed("素材不存在或不属于该项目。")
    duration = int(command["duration_ticks"])
    source_in = int(command.get("source_in_ticks") or 0)
    element = {
        "id": command.get("element_id") or new_id("el"),
        "type": element_type,
        "track_id": track["id"],
        "asset_id": asset_id,
        "start_ticks": int(command["at_ticks"]),
        "duration_ticks": duration,
        "source_in_ticks": source_in,
        "source_out_ticks": source_in + duration,
        "volume_millipercent": 100_000,
        "speed_millipercent": 100_000,
        "text": None,
        "caption_language": None,
        "effects": [],
        "mask": None,
        "animations": {"channels": {}},
        "transition_in": None,
        "transition_out": None,
    }
    track["elements"].append(element)


def _insert_caption(document: dict[str, Any], command: dict[str, Any]) -> None:
    track = docs.find_track(document, command["track_id"])
    if track is None:
        raise ValidationFailed("轨道不存在。")
    if track.get("kind") != "caption":
        raise ValidationFailed("字幕只能插入字幕轨道。")
    element = {
        "id": command.get("element_id") or new_id("el"),
        "type": "caption",
        "track_id": track["id"],
        "asset_id": None,
        "start_ticks": int(command["at_ticks"]),
        "duration_ticks": int(command["duration_ticks"]),
        "source_in_ticks": 0,
        "source_out_ticks": int(command["duration_ticks"]),
        "volume_millipercent": 100_000,
        "speed_millipercent": 100_000,
        "text": str(command["text"]),
        "caption_language": command.get("caption_language") or "zh-CN",
        "effects": [],
        "mask": None,
        "animations": {"channels": {}},
        "transition_in": None,
        "transition_out": None,
    }
    track["elements"].append(element)


def _move_elements(document: dict[str, Any], command: dict[str, Any]) -> None:
    delta = int(command["delta_ticks"])
    target_track = None
    if command.get("track_id"):
        target_track = docs.find_track(document, command["track_id"])
        if target_track is None:
            raise ValidationFailed("目标轨道不存在。")
    for element_id in command["element_ids"]:
        found = docs.find_element(document, element_id)
        if found is None:
            raise ValidationFailed("元素不存在。")
        track, element = found
        element["start_ticks"] = max(0, int(element["start_ticks"]) + delta)
        if target_track is not None and target_track["id"] != track["id"]:
            if target_track.get("kind") != track.get("kind"):
                raise ValidationFailed("不能跨轨道类型移动元素。")
            track["elements"] = [item for item in track["elements"] if item["id"] != element_id]
            element["track_id"] = target_track["id"]
            target_track["elements"].append(element)


def _deep_copy_element(element: dict[str, Any]) -> dict[str, Any]:
    """Same per-field copy `_split_element` needs: `dict(element)` still shares
    the `effects` list (and each effect's `params`) and the `animations.channels`
    map, which later commands mutate in place. `mask`/transitions are always
    replaced wholesale, so a shallow copy of those is enough."""
    copied = dict(element)
    copied["effects"] = [
        {**effect, "params": dict(effect.get("params") or {})}
        for effect in element.get("effects") or []
    ]
    copied["animations"] = {
        "channels": {
            prop: {"kind": channel["kind"], "points": [dict(p) for p in channel["points"]]}
            for prop, channel in (element.get("animations") or {}).get("channels", {}).items()
        }
    }
    copied["mask"] = dict(element["mask"]) if element.get("mask") else None
    for edge in ("transition_in", "transition_out"):
        copied[edge] = dict(element[edge]) if element.get(edge) else None
    return copied


def _duplicate_elements(document: dict[str, Any], command: dict[str, Any]) -> None:
    """Copies each named element onto its own track with a fresh id. Without
    `delta_ticks` the copy lands right after the source's own end (the
    "Ctrl+D" case); with it, the copy is shifted by that amount from the
    source's start (the "paste at playhead" case). Everything else — trims,
    effects, mask, keyframes, transitions — comes along verbatim."""
    delta = command.get("delta_ticks")
    # Client-supplied ids (like `insert_clip.element_id`) let an optimistic
    # frontend predict the copy's id and target it in a follow-up batch
    # before this one has round-tripped; omitted, the server mints them.
    new_ids: list[str | None] = list(command.get("new_element_ids") or [])
    copies: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, element_id in enumerate(command["element_ids"]):
        found = docs.find_element(document, element_id)
        if found is None:
            raise ValidationFailed("元素不存在。")
        track, element = found
        copied = _deep_copy_element(element)
        requested = new_ids[index] if index < len(new_ids) else None
        if requested and docs.find_element(document, requested) is not None:
            raise ValidationFailed("元素 id 已存在。")
        copied["id"] = requested or new_id("el")
        start = int(element["start_ticks"])
        if delta is None:
            copied["start_ticks"] = start + int(element["duration_ticks"])
        else:
            copied["start_ticks"] = max(0, start + int(delta))
        copies.append((track, copied))
    for track, copied in copies:
        track["elements"].append(copied)


def _split_element(document: dict[str, Any], command: dict[str, Any]) -> None:
    found = docs.find_element(document, command["element_id"])
    if found is None:
        raise ValidationFailed("元素不存在。")
    track, element = found
    at_ticks = int(command["at_ticks"])
    start = int(element["start_ticks"])
    duration = int(element["duration_ticks"])
    if at_ticks <= start or at_ticks >= start + duration:
        raise ValidationFailed("拆分点必须落在元素内部。")
    left_duration = at_ticks - start
    right_duration = duration - left_duration
    source_in = int(element.get("source_in_ticks") or 0)
    right = dict(element)
    # A shallow dict copy still shares the `effects` list object, and the
    # `animations.channels` dict, with the original — add_effect/remove_effect
    # and set_keyframe/delete_keyframe/clear_keyframes all mutate a key on
    # one of those shared objects in place, which would otherwise leak
    # across both split halves. `mask` needs no such copy: every write to it
    # replaces the whole value rather than mutating it.
    right["effects"] = [dict(effect) for effect in element.get("effects") or []]
    right["animations"] = {
        "channels": {
            prop: {"kind": channel["kind"], "points": list(channel["points"])}
            for prop, channel in (element.get("animations") or {}).get("channels", {}).items()
        }
    }
    requested = command.get("new_element_id")
    if requested and docs.find_element(document, requested) is not None:
        raise ValidationFailed("元素 id 已存在。")
    right["id"] = requested or new_id("el")
    right["start_ticks"] = at_ticks
    right["duration_ticks"] = right_duration
    right["source_in_ticks"] = source_in + left_duration
    right["source_out_ticks"] = source_in + duration
    # The split point is a brand-new internal edge on both halves — the
    # original's transition_in stays on the left half (its start didn't
    # move) and transition_out stays on the right half (inherited by the
    # dict copy above, since its end didn't move either); neither edge
    # transition should duplicate onto the new cut point.
    right["transition_in"] = None
    element["duration_ticks"] = left_duration
    element["source_out_ticks"] = source_in + left_duration
    element["transition_out"] = None
    track["elements"].append(right)
