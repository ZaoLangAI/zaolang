"""Validated EditCommand batches. Manual UI, AI and MCP share this contract."""

from __future__ import annotations

from typing import Any

from app.domain.editor import document as docs
from app.domain.editor.time import MAX_COMMANDS_PER_BATCH, assert_safe_ticks
from app.domain.errors import BatchRolledBack, ValidationFailed
from app.models.base import new_id

ALLOWED_TYPES = frozenset(
    {
        "insert_clip",
        "delete_elements",
        "move_elements",
        "trim_element",
        "split_element",
        "set_clip_volume",
        "set_clip_speed",
        "insert_caption",
        "update_caption",
        "set_canvas",
        "set_brand_overlay",
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
        },
        "delete_elements": {"element_ids"},
        "move_elements": {"element_ids", "delta_ticks", "track_id"},
        "trim_element": {
            "element_id",
            "start_ticks",
            "duration_ticks",
            "source_in_ticks",
            "source_out_ticks",
        },
        "split_element": {"element_id", "at_ticks"},
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
    if command_type == "delete_elements":
        ids = command.get("element_ids")
        if not isinstance(ids, list) or not ids:
            raise ValidationFailed("element_ids 不能为空。")
    if command_type == "insert_clip" and not command.get("asset_id"):
        raise ValidationFailed("insert_clip 需要 asset_id。")
    if command_type == "insert_caption" and not str(command.get("text") or "").strip():
        raise ValidationFailed("字幕不能为空。")


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


def _insert_clip(
    document: dict[str, Any], command: dict[str, Any], *, known_assets: set[str]
) -> None:
    track = docs.find_track(document, command["track_id"])
    if track is None:
        raise ValidationFailed("轨道不存在。")
    asset_id = str(command["asset_id"])
    if known_assets and asset_id not in known_assets:
        raise ValidationFailed("素材不存在或不属于该项目。")
    duration = int(command["duration_ticks"])
    source_in = int(command.get("source_in_ticks") or 0)
    element = {
        "id": command.get("element_id") or new_id("el"),
        "type": "clip",
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
    }
    track["elements"].append(element)


def _insert_caption(document: dict[str, Any], command: dict[str, Any]) -> None:
    track = docs.find_track(document, command["track_id"])
    if track is None:
        raise ValidationFailed("轨道不存在。")
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
            track["elements"] = [item for item in track["elements"] if item["id"] != element_id]
            element["track_id"] = target_track["id"]
            target_track["elements"].append(element)


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
    right["id"] = new_id("el")
    right["start_ticks"] = at_ticks
    right["duration_ticks"] = right_duration
    right["source_in_ticks"] = source_in + left_duration
    right["source_out_ticks"] = source_in + duration
    element["duration_ticks"] = left_duration
    element["source_out_ticks"] = source_in + left_duration
    track["elements"].append(right)
