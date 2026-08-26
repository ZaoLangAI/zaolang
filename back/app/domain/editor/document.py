"""Canonical timeline document. Never stores object keys or signed URLs."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.domain.editor.time import MAX_DOCUMENT_BYTES, MAX_ELEMENTS_PER_DOCUMENT, assert_safe_ticks

ENGINE = "zaolang-canonical"
SCHEMA_VERSION = 1


def _track(track_id: str, kind: str) -> dict[str, Any]:
    return {"id": track_id, "kind": kind, "elements": [], "order": 0, "label": None, "muted": False}


def empty_document(*, width: int = 1080, height: int = 1920) -> dict[str, Any]:
    video_track = _track("trk_video", "video")
    audio_track = _track("trk_audio", "audio")
    caption_track = _track("trk_caption", "caption")
    overlay_track = _track("trk_overlay", "overlay")
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": ENGINE,
        "canvas": {"width": width, "height": height, "fps_num": 30, "fps_den": 1},
        "tracks": [video_track, audio_track, caption_track, overlay_track],
        "brand_overlay": None,
    }


def clone_document(document: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(document)


def iter_elements(document: dict[str, Any]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for track in document.get("tracks") or []:
        for element in track.get("elements") or []:
            elements.append(element)
    return elements


def element_count(document: dict[str, Any]) -> int:
    return len(iter_elements(document))


def find_track(document: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    for track in document.get("tracks") or []:
        if track.get("id") == track_id:
            return track
    return None


def find_element(
    document: dict[str, Any], element_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for track in document.get("tracks") or []:
        for element in track.get("elements") or []:
            if element.get("id") == element_id:
                return track, element
    return None


def duration_ticks(document: dict[str, Any]) -> int:
    end = 0
    for element in iter_elements(document):
        start = int(element.get("start_ticks") or 0)
        length = int(element.get("duration_ticks") or 0)
        end = max(end, start + length)
    return end


def _normalize_track(track: dict[str, Any]) -> dict[str, Any]:
    """Backfills `order`/`label`/`muted` on tracks from before these fields existed.

    Revisions are immutable full snapshots with no migration path, so old
    stored documents must upgrade transparently through this function rather
    than through a schema-version bump or a one-off backfill script.
    """
    return {
        **track,
        "order": int(track.get("order") or 0),
        "label": track.get("label"),
        "muted": bool(track.get("muted") or False),
    }


def canonicalize(document: dict[str, Any]) -> dict[str, Any]:
    payload = clone_document(document)
    payload["schema_version"] = SCHEMA_VERSION
    payload["engine"] = ENGINE
    tracks = []
    for track in payload.get("tracks") or []:
        normalized = _normalize_track(track)
        elements = sorted(
            normalized.get("elements") or [],
            key=lambda item: (item.get("start_ticks", 0), item.get("id", "")),
        )
        tracks.append({**normalized, "elements": elements})
    # `order` is the meaningful z-order for video tracks (and stable UI row
    # order for others); `id` only breaks ties within the same order.
    payload["tracks"] = sorted(tracks, key=lambda item: (item.get("order", 0), item.get("id", "")))
    return payload


def content_hash(document: dict[str, Any], asset_bindings: list[Any]) -> str:
    canonical = {"document": canonicalize(document), "asset_bindings": asset_bindings}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("时间线文档超过 5MB 上限。")
    if element_count(document) > MAX_ELEMENTS_PER_DOCUMENT:
        raise ValueError("时间线元素超过 5000 上限。")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_document(document: dict[str, Any]) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("不支持的时间线 schema。")
    canvas = document.get("canvas") or {}
    for key in ("width", "height", "fps_num", "fps_den"):
        if int(canvas.get(key) or 0) <= 0:
            raise ValueError(f"画布 {key} 不合法。")
    seen: set[str] = set()
    for element in iter_elements(document):
        element_id = str(element.get("id") or "")
        if not element_id or element_id in seen:
            raise ValueError("元素 id 缺失或重复。")
        seen.add(element_id)
        assert_safe_ticks(int(element.get("start_ticks") or 0), label="start_ticks")
        assert_safe_ticks(int(element.get("duration_ticks") or 0), label="duration_ticks")
        if int(element.get("duration_ticks") or 0) <= 0:
            raise ValueError("元素时长必须为正。")


def timeline_summary(document: dict[str, Any]) -> dict[str, Any]:
    tracks = []
    for track in document.get("tracks") or []:
        tracks.append(
            {
                "id": track.get("id"),
                "kind": track.get("kind"),
                "order": track.get("order"),
                "label": track.get("label"),
                "muted": track.get("muted"),
                "element_count": len(track.get("elements") or []),
                "elements": [
                    {
                        "id": element.get("id"),
                        "type": element.get("type"),
                        "asset_id": element.get("asset_id"),
                        "start_ticks": element.get("start_ticks"),
                        "duration_ticks": element.get("duration_ticks"),
                    }
                    for element in (track.get("elements") or [])
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": document.get("canvas"),
        "duration_ticks": duration_ticks(document),
        "tracks": tracks,
        "brand_overlay": document.get("brand_overlay"),
    }
