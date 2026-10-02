"""Validates, bounds and completes a blocking document.

Every write into `DramaEpisode.blocking_json` goes through
`sanitize_blocking` — a model's `blocking_derive` reply, a manual drag edit
from the browser, and a settings change alike — the same role
`copywriter._sanitize_script` plays for `script_json`.

Beyond clamping, the sanitizer is what keeps a blockout *aligned* with its
script: sets are forced one-per-scene-heading, the cast is forced to the
script's characters (links copied from the script, never from the model),
and segments are forced to exactly `ordered_segments(script)`'s keys, in
order. Anything the reply left out is completed from the previous version
(so the model may answer with only what it changed) and, failing that,
from a deterministic default staging.

Coordinates: metres, stage centred on the origin, `y` up. Facing is a yaw
in degrees where 0 looks toward +z (the default camera side) and 90 toward
+x (screen right).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.blocking import vocabulary as v
from app.domain.blocking.camera_language import CameraCue, normalize_token, parse_camera_text
from app.domain.blocking.segments import (
    ScriptSegment,
    default_target_duration,
    estimate_segment_seconds,
    ordered_segments,
    script_hash,
    segment_source_hash,
)

BLOCKING_VERSION = 1
SanitizeMode = Literal["llm", "manual"]

_HASH16 = re.compile(r"^[0-9a-f]{16}$")
_DEFAULT_STAGE = 10.0
_CAST_SPACING = 1.2
_FACING_TARGET_CAMERA = "camera"
_IN_PLACE_ACTIONS = frozenset({"talk", "point", "wave", "hug", "fight", "turn"})


@dataclass(slots=True)
class SanitizeResult:
    document: dict[str, Any]
    duration_warning: str | None = None
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------


def _num(raw: Any, default: float, lo: float, hi: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return round(min(max(value, lo), hi), 3)


def _choice(raw: Any, allowed: tuple[str, ...], default: str, kind: str = "") -> str:
    """The documented token, tolerating the Chinese label, film-school
    shorthand and spelling variants different vendors' models produce
    (`camera_language.normalize_token`)."""
    token = normalize_token(raw, allowed, kind)
    return token if token is not None else default


def _label(raw: Any) -> str:
    return str(raw or "").strip()[: v.MAX_LABEL_LEN]


def _ident(raw: Any) -> str:
    return str(raw or "").strip()[: v.MAX_ID_LEN]


def _vec(raw: Any, default: list[float], lo: float, hi: float) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != len(default):
        return list(default)
    return [_num(item, default[i], lo, hi) for i, item in enumerate(raw)]


def _dicts(raw: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw[:limit] if isinstance(item, dict)]


# --------------------------------------------------------------------------
# Sets
# --------------------------------------------------------------------------


def _default_set(set_id: str, heading: str) -> dict[str, Any]:
    return {
        "id": set_id,
        "heading": heading,
        "ground": "floor",
        "width_m": _DEFAULT_STAGE,
        "depth_m": _DEFAULT_STAGE,
        "props": [],
        "anchors": [{"id": "center", "label": "中心", "x": 0.0, "z": 0.0}],
    }


def _sanitize_set(raw: dict[str, Any], *, set_id: str, heading: str) -> dict[str, Any]:
    width = _num(raw.get("width_m"), _DEFAULT_STAGE, v.STAGE_MIN_METERS, v.STAGE_MAX_METERS)
    depth = _num(raw.get("depth_m"), _DEFAULT_STAGE, v.STAGE_MIN_METERS, v.STAGE_MAX_METERS)
    half_w, half_d = width / 2, depth / 2

    props: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(_dicts(raw.get("props"), v.MAX_PROPS_PER_SET)):
        prop_id = _ident(item.get("id")) or f"p{index + 1}"
        if prop_id in seen:
            prop_id = f"p{index + 1}_{len(seen)}"
        seen.add(prop_id)
        position = _vec(item.get("position"), [0.0, 0.0, 0.0], -v.STAGE_MAX_METERS, 30.0)
        position[0] = min(max(position[0], -half_w), half_w)
        position[1] = max(position[1], 0.0)
        position[2] = min(max(position[2], -half_d), half_d)
        props.append(
            {
                "id": prop_id,
                "primitive": _choice(item.get("primitive"), v.PRIMITIVES, "box"),
                "label": _label(item.get("label")),
                "color_role": _choice(item.get("color_role"), v.COLOR_ROLES, "furniture"),
                "position": position,
                "rotation_y_deg": _num(item.get("rotation_y_deg"), 0.0, -360.0, 360.0),
                "scale": _vec(item.get("scale"), [1.0, 1.0, 1.0], 0.05, v.STAGE_MAX_METERS),
            }
        )

    anchors: list[dict[str, Any]] = []
    anchor_ids: set[str] = set()
    for index, item in enumerate(_dicts(raw.get("anchors"), v.MAX_ANCHORS_PER_SET)):
        anchor_id = _ident(item.get("id")) or f"a{index + 1}"
        if anchor_id in anchor_ids:
            continue
        anchor_ids.add(anchor_id)
        x, z = _xz(item, half_w, half_d)
        anchors.append({"id": anchor_id, "label": _label(item.get("label")), "x": x, "z": z})
    if "center" not in anchor_ids and len(anchors) < v.MAX_ANCHORS_PER_SET:
        anchors.append({"id": "center", "label": "中心", "x": 0.0, "z": 0.0})

    return {
        "id": set_id,
        "heading": heading,
        "ground": _choice(raw.get("ground"), v.GROUNDS, "floor"),
        "width_m": width,
        "depth_m": depth,
        "props": props,
        "anchors": anchors,
    }


def _xz(raw: Any, half_w: float, half_d: float) -> tuple[float, float]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        x_raw, z_raw = raw
    elif isinstance(raw, dict):
        position = raw.get("position")
        if isinstance(position, (list, tuple)) and len(position) in (2, 3):
            x_raw, z_raw = position[0], position[-1]
        else:
            x_raw, z_raw = raw.get("x"), raw.get("z")
    else:
        x_raw, z_raw = None, None
    return _num(x_raw, 0.0, -half_w, half_w), _num(z_raw, 0.0, -half_d, half_d)


def _sanitize_sets(
    raw: dict[str, Any], *, script: dict[str, Any], previous: dict[str, Any] | None
) -> list[dict[str, Any]]:
    headings: list[str] = []
    for scene in script.get("scenes") or []:
        heading = str(scene.get("heading") or "") if isinstance(scene, dict) else ""
        if heading and heading not in headings:
            headings.append(heading)
    headings = headings[: v.MAX_SETS]

    raw_sets = _dicts(raw.get("sets"), v.MAX_SETS * 2)
    prev_sets = _dicts((previous or {}).get("sets"), v.MAX_SETS * 2)
    raw_by_heading = {str(s.get("heading") or ""): s for s in raw_sets}
    prev_by_heading = {str(s.get("heading") or ""): s for s in prev_sets}
    # A heading rename orphans its set; when the scene count is unchanged
    # the positional match is almost always the renamed scene.
    positional = len(prev_sets) == len(headings)

    sets: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        set_id = f"s{index + 1}"
        source = raw_by_heading.get(heading) or prev_by_heading.get(heading)
        if source is None and positional and not raw_by_heading.get(heading):
            candidate = prev_sets[index]
            if str(candidate.get("heading") or "") not in headings:
                source = candidate
        sets.append(
            _sanitize_set(source, set_id=set_id, heading=heading)
            if source is not None
            else _default_set(set_id, heading)
        )
    return sets


# --------------------------------------------------------------------------
# Cast
# --------------------------------------------------------------------------


def _sanitize_cast(
    raw: dict[str, Any], *, script: dict[str, Any], previous: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Returns the cast plus an alias map (any id *or name* the reply used
    → the canonical cast id) for resolving segment references."""
    raw_cast = _dicts(raw.get("cast"), v.MAX_CAST * 3)
    prev_cast = _dicts((previous or {}).get("cast"), v.MAX_CAST * 3)
    raw_by_name = {str(c.get("name") or ""): c for c in raw_cast}
    prev_by_name = {str(c.get("name") or ""): c for c in prev_cast}

    cast: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    used_ids: set[str] = set()
    used_colors: set[int] = set()
    characters = [c for c in script.get("characters") or [] if isinstance(c, dict)]
    for index, character in enumerate(characters[: v.MAX_CAST]):
        name = str(character.get("name") or "").strip()
        if not name:
            continue
        mine = raw_by_name.get(name) or {}
        before = prev_by_name.get(name) or {}
        cast_id = ""
        for candidate in (_ident(mine.get("id")), _ident(before.get("id")), f"c{index + 1}"):
            if candidate and candidate not in used_ids:
                cast_id = candidate
                break
        if not cast_id:
            cast_id = f"c{index + 1}_{len(used_ids)}"
        used_ids.add(cast_id)

        color: int | None = None
        for candidate_color in (mine.get("color_index"), before.get("color_index")):
            if (
                isinstance(candidate_color, int)
                and 0 <= candidate_color < v.CAST_COLOR_COUNT
                and candidate_color not in used_colors
            ):
                color = candidate_color
                break
        if color is None:
            color = next(
                (c for c in range(v.CAST_COLOR_COUNT) if c not in used_colors),
                index % v.CAST_COLOR_COUNT,
            )
        used_colors.add(color)

        height_source = mine.get("height_m", before.get("height_m"))
        ref = character.get("character_ref_id")
        cast.append(
            {
                "id": cast_id,
                "name": name,
                "character_ref_id": str(ref) if ref else None,
                "color_index": color,
                "height_m": _num(height_source, 1.7, v.CAST_MIN_HEIGHT_M, v.CAST_MAX_HEIGHT_M),
            }
        )
        aliases[cast_id] = cast_id
        aliases[name] = cast_id
        for alias in (_ident(mine.get("id")), _ident(before.get("id"))):
            if alias and alias not in aliases:
                aliases[alias] = cast_id
    return cast, aliases


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------


def _mark(
    raw: Any, *, anchors: dict[str, dict[str, Any]], set_: dict[str, Any]
) -> dict[str, Any] | None:
    half_w, half_d = set_["width_m"] / 2, set_["depth_m"] / 2
    if isinstance(raw, str):
        anchor = anchors.get(raw.strip())
        if anchor is None:
            return None
        return {"anchor": anchor["id"], "x": anchor["x"], "z": anchor["z"]}
    if isinstance(raw, dict) and isinstance(raw.get("anchor"), str):
        anchor = anchors.get(raw["anchor"].strip())
        if anchor is not None:
            return {"anchor": anchor["id"], "x": anchor["x"], "z": anchor["z"]}
    if isinstance(raw, (list, tuple, dict)):
        if isinstance(raw, dict) and raw.get("x") is None and raw.get("position") is None:
            return None
        x, z = _xz(raw, half_w, half_d)
        return {"anchor": None, "x": x, "z": z}
    return None


def _facing(raw: Any, *, targets: set[str], aliases: dict[str, str]) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"target": None, "deg": _num(raw, 0.0, -360.0, 360.0)}
    if isinstance(raw, dict):
        if raw.get("target") is not None:
            return _facing(raw.get("target"), targets=targets, aliases=aliases) or (
                {"target": None, "deg": _num(raw.get("deg"), 0.0, -360.0, 360.0)}
                if raw.get("deg") is not None
                else None
            )
        if raw.get("deg") is not None:
            return {"target": None, "deg": _num(raw.get("deg"), 0.0, -360.0, 360.0)}
        return None
    if isinstance(raw, str):
        value = raw.strip()
        resolved = aliases.get(value, value)
        if resolved in targets:
            return {"target": resolved, "deg": 0.0}
    return None


def _segment_cast_ids(segment: ScriptSegment, cast: list[dict[str, Any]]) -> list[str]:
    """Who a default staging puts on set: speakers first, then any cast
    name mentioned in the segment's action/camera text."""
    ids: list[str] = []
    by_name = {c["name"]: c["id"] for c in cast}
    for block in segment.blocks:
        name = str(block.get("character") or "")
        if block.get("type") == "dialogue" and name in by_name and by_name[name] not in ids:
            ids.append(by_name[name])
    for block in segment.blocks:
        text = str(block.get("text") or "")
        for member in cast:
            if member["name"] and member["name"] in text and member["id"] not in ids:
                ids.append(member["id"])
    return ids


def _default_start(cast_ids: list[str]) -> list[dict[str, Any]]:
    count = len(cast_ids)
    entries = []
    for index, cast_id in enumerate(cast_ids):
        x = round((index - (count - 1) / 2) * _CAST_SPACING, 3)
        if count == 2:
            # Two people talking face each other, not the lens.
            face = {"target": cast_ids[1 - index], "deg": 0.0}
        else:
            face = {"target": _FACING_TARGET_CAMERA, "deg": 0.0}
        entries.append(
            {
                "cast_id": cast_id,
                "at": {"anchor": None, "x": x, "z": 0.0},
                "face": face,
                "action": "stand",
            }
        )
    return entries


def _default_shot(cast_ids: list[str]) -> dict[str, Any]:
    return {
        "t0": 0.0,
        "transition": "cut",
        "size": "medium" if len(cast_ids) <= 2 else "full",
        "lens_mm": 35,
        "height": "eye",
        "side": "front",
        "subject": cast_ids[0] if cast_ids else None,
        "over": None,
        "move": {"preset": "static", "intensity": 0.5, "ease": "in_out"},
    }


def _sanitize_shot(
    raw: Any,
    *,
    cast_ids: set[str],
    anchors: set[str],
    aliases: dict[str, str],
    fallback: dict,
    time_scale: float = 1.0,
    duration: float = 0.0,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(fallback)
    subject_raw = str(raw.get("subject") or "").strip()
    subject: str | None = aliases.get(subject_raw, subject_raw)
    if subject not in cast_ids and subject not in anchors:
        subject = fallback.get("subject")
    over_raw = str(raw.get("over") or "").strip()
    over: str | None = aliases.get(over_raw, over_raw)
    side = _choice(raw.get("side"), v.CAMERA_SIDES, "front", "side")
    if over not in cast_ids or over == subject:
        over = None
    if side.startswith("ots") and over is None:
        side = "front"
    # `move` should be an object, but a bare preset string (or the preset at
    # the shot's top level) is common enough across vendors to accept.
    raw_move = raw.get("move")
    move: dict[str, Any] = (
        raw_move
        if isinstance(raw_move, dict)
        else {"preset": raw_move, "intensity": raw.get("intensity"), "ease": raw.get("ease")}
    )
    preset = move.get("preset", raw.get("preset"))
    lens_raw = raw.get("lens_mm", raw.get("lens"))
    t0 = _num(raw.get("t0", raw.get("start")), 0.0, 0.0, 120.0) * time_scale
    return {
        "t0": round(min(t0, duration) if duration else t0, 2),
        "transition": _choice(raw.get("transition"), v.SHOT_TRANSITIONS, "cut"),
        "size": _choice(raw.get("size"), v.SHOT_SIZES, fallback["size"], "size"),
        "lens_mm": int(_num(lens_raw, fallback["lens_mm"], v.LENS_MIN_MM, v.LENS_MAX_MM)),
        "height": _choice(raw.get("height"), v.CAMERA_HEIGHTS, "eye", "height"),
        "side": side,
        "subject": subject,
        "over": over,
        "move": {
            "preset": _choice(preset, v.CAMERA_MOVES, "static", "move"),
            "intensity": _num(move.get("intensity"), 0.5, 0.0, 1.0),
            "ease": _choice(move.get("ease"), v.MOVE_EASES, "in_out"),
        },
    }


def _normalize_shot_times(shots: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Time order, first shot at 0, every shot at least `MIN_SHOT_SECONDS`
    long, at most `MAX_SHOTS_PER_SEGMENT`."""
    ordered = sorted(shots, key=lambda shot: shot["t0"])
    kept: list[dict[str, Any]] = []
    for shot in ordered:
        if not kept:
            kept.append({**shot, "t0": 0.0})
            continue
        if shot["t0"] - kept[-1]["t0"] < v.MIN_SHOT_SECONDS:
            continue
        if duration - shot["t0"] < v.MIN_SHOT_SECONDS:
            continue
        kept.append(shot)
    return kept[: v.MAX_SHOTS_PER_SEGMENT]


def _raw_shots(raw: dict[str, Any]) -> list[Any]:
    shots = raw.get("shots")
    if isinstance(shots, list) and shots:
        return shots
    legacy = raw.get("shot")
    if isinstance(legacy, list):
        return legacy
    return [legacy] if isinstance(legacy, dict) else []


def _block_weights(blocks: tuple[dict[str, Any], ...]) -> list[float]:
    """Rough screen time per block — where in the clip a camera block lands."""
    weights = []
    for block in blocks:
        kind = block.get("type")
        text = str(block.get("text") or "")
        if kind == "dialogue":
            weights.append(max(1.0, len(text) / 3.5))
        elif kind == "action":
            weights.append(3.0)
        else:
            weights.append(0.0)
    return weights


def camera_cues(segment: ScriptSegment) -> list[tuple[float, CameraCue]]:
    """Each non-empty script camera block with the fraction (0–1) of the
    segment at which it takes effect."""
    weights = _block_weights(segment.blocks)
    total = sum(weights) or 1.0
    cues: list[tuple[float, CameraCue]] = []
    elapsed = 0.0
    for block, weight in zip(segment.blocks, weights, strict=True):
        if block.get("type") == "camera":
            cue = parse_camera_text(str(block.get("text") or ""))
            if not cue.empty:
                cues.append((elapsed / total, cue))
        elapsed += weight
    return cues


def _reconcile_with_script(
    shots: list[dict[str, Any]], segment: ScriptSegment, duration: float
) -> list[dict[str, Any]]:
    """The script's camera blocks are authoritative for shot size and move:
    one shot per camera block, in order, whatever the model answered. The
    model still owns subject, angle, height, lens and exact timing when it
    produced a matching shot — this only corrects what the script states.
    """
    cues = camera_cues(segment)
    if not cues:
        return shots
    reconciled: list[dict[str, Any]] = []
    for index, (fraction, cue) in enumerate(cues):
        base = dict(shots[index] if index < len(shots) else shots[-1])
        base["move"] = dict(base["move"])
        if index >= len(shots) or index == 0:
            base["t0"] = 0.0 if index == 0 else round(fraction * duration * 2) / 2
        if cue.size:
            base["size"] = cue.size
        if cue.preset:
            if base["move"]["preset"] != cue.preset:
                base["move"]["intensity"] = cue.intensity
            base["move"]["preset"] = cue.preset
        if index > 0:
            previous = reconciled[-1]
            base["transition"] = "cut" if base["size"] != previous["size"] else "continuous"
        reconciled.append(base)
    return reconciled


def _shot_signature(shots: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """What "the model left the camera alone" compares — the grammar, not
    timing jitter."""
    return [
        (
            shot["size"],
            shot["lens_mm"],
            shot["height"],
            shot["side"],
            shot["subject"],
            shot["over"],
            shot["move"]["preset"],
        )
        for shot in shots
    ]


def _camera_pose(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    position = raw.get("position")
    target = raw.get("target")
    if not isinstance(position, (list, tuple)) or not isinstance(target, (list, tuple)):
        return None
    return {
        "position": _vec(position, [0.0, 1.6, 5.0], -100.0, 100.0),
        "target": _vec(target, [0.0, 1.2, 0.0], -100.0, 100.0),
        "fov": _num(raw.get("fov"), 40.0, 10.0, 100.0),
    }


def _sanitize_override(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    start = _camera_pose(raw.get("start"))
    if start is None:
        return None
    return {"start": start, "end": _camera_pose(raw.get("end"))}


def _sanitize_segment(
    raw: dict[str, Any],
    *,
    segment: ScriptSegment,
    set_: dict[str, Any],
    cast: list[dict[str, Any]],
    aliases: dict[str, str],
    duration: float,
    reconcile: bool = False,
) -> dict[str, Any]:
    cast_ids = {c["id"] for c in cast}
    anchors = {a["id"]: a for a in set_["anchors"]}
    targets = cast_ids | set(anchors) | {_FACING_TARGET_CAMERA}

    start: list[dict[str, Any]] = []
    placed: set[str] = set()
    raw_start = raw.get("start")
    if isinstance(raw_start, dict):
        # The prompt's shape is a map; a list of entries is accepted too.
        raw_start = [
            {"cast_id": key, **value} for key, value in raw_start.items() if isinstance(value, dict)
        ]
    for item in _dicts(raw_start, v.MAX_CAST * 2):
        cast_id = aliases.get(str(item.get("cast_id") or "").strip())
        if cast_id is None or cast_id in placed:
            continue
        at = _mark(item.get("at"), anchors=anchors, set_=set_)
        if at is None:
            at = {"anchor": None, "x": round((len(placed) - 0.5) * _CAST_SPACING, 3), "z": 0.0}
        placed.add(cast_id)
        start.append(
            {
                "cast_id": cast_id,
                "at": at,
                "face": _facing(
                    item.get("face", item.get("facing")), targets=targets, aliases=aliases
                )
                or {"target": _FACING_TARGET_CAMERA, "deg": 0.0},
                "action": _choice(item.get("action"), v.CAST_ACTIONS, "stand", "action"),
            }
        )
    if not start:
        start = _default_start(_segment_cast_ids(segment, cast))
        placed = {entry["cast_id"] for entry in start}

    raw_duration = _num(raw.get("duration_s"), duration, 0.5, 120.0)
    scale = duration / raw_duration if raw_duration > 0 else 1.0
    beats: list[dict[str, Any]] = []
    for item in _dicts(raw.get("beats"), v.MAX_BEATS_PER_SEGMENT * 2):
        cast_id = aliases.get(str(item.get("cast_id") or "").strip())
        if cast_id is None or cast_id not in placed:
            continue
        t0 = _num(item.get("t0"), 0.0, 0.0, raw_duration) * scale
        t1 = _num(item.get("t1"), t0 / scale + 1.0, 0.0, raw_duration) * scale
        if t1 - t0 < 0.2:
            t1 = min(duration, t0 + 1.0)
        if t1 <= t0:
            continue
        action = _choice(item.get("action"), v.CAST_ACTIONS, "stand", "action")
        beat: dict[str, Any] = {
            "cast_id": cast_id,
            "t0": round(t0, 2),
            "t1": round(t1, 2),
            "action": action,
            # A gesture happens where the person stands; models routinely
            # attach a `to` to every beat, which would turn「说话」into a walk.
            "to": None
            if action in _IN_PLACE_ACTIONS
            else _mark(item.get("to"), anchors=anchors, set_=set_),
            "face": _facing(item.get("face", item.get("facing")), targets=targets, aliases=aliases),
        }
        beats.append(beat)
    beats.sort(key=lambda b: (b["cast_id"], b["t0"]))
    # One cast member does one thing at a time: an overlapping later beat is
    # trimmed to start where the earlier one ends, or dropped.
    trimmed: list[dict[str, Any]] = []
    last_end: dict[str, float] = {}
    for beat in beats:
        start_at = max(beat["t0"], last_end.get(beat["cast_id"], 0.0))
        if beat["t1"] - start_at < 0.2:
            continue
        beat["t0"] = round(start_at, 2)
        last_end[beat["cast_id"]] = beat["t1"]
        trimmed.append(beat)
    trimmed.sort(key=lambda b: (b["t0"], b["cast_id"]))
    trimmed = trimmed[: v.MAX_BEATS_PER_SEGMENT]

    placed_ids = [entry["cast_id"] for entry in start]
    fallback_shot = _default_shot(placed_ids)
    shots = [
        _sanitize_shot(
            item,
            cast_ids=set(placed_ids),
            anchors=set(anchors),
            aliases=aliases,
            fallback=fallback_shot,
            time_scale=scale,
            duration=duration,
        )
        for item in _raw_shots(raw)[: v.MAX_SHOTS_PER_SEGMENT * 2]
    ] or [dict(fallback_shot)]
    shots = _normalize_shot_times(shots, duration)
    if reconcile:
        shots = _normalize_shot_times(_reconcile_with_script(shots, segment, duration), duration)
    return {
        "key": segment.key,
        "heading": segment.heading,
        "set_id": set_["id"],
        "source_hash": segment_source_hash(segment),
        "duration_s": duration,
        "start": start,
        "beats": trimmed,
        "shots": shots,
        "camera_override": None,
    }


# --------------------------------------------------------------------------
# Durations
# --------------------------------------------------------------------------


def fit_durations(raw: list[float], target: int) -> tuple[list[int], str | None]:
    """Scales per-segment durations toward `target` inside the per-segment
    window, then rounds to whole seconds (largest remainder) so the sum is
    exact whenever the window allows it."""
    count = len(raw)
    if count == 0:
        return [], None
    lo, hi = float(v.SEGMENT_MIN_SECONDS), float(v.SEGMENT_MAX_SECONDS)
    values = [min(max(x if x > 0 else lo, lo), hi) for x in raw]
    warning: str | None = None
    if target < lo * count:
        warning = (
            f"目标总时长 {target} 秒过短：{count} 个分镜段每段至少 "
            f"{v.SEGMENT_MIN_SECONDS} 秒，最短 {int(lo * count)} 秒。"
        )
        return [int(lo)] * count, warning
    if target > hi * count:
        warning = (
            f"目标总时长 {target} 秒过长：{count} 个分镜段每段至多 "
            f"{v.SEGMENT_MAX_SECONDS} 秒，最长 {int(hi * count)} 秒，可在文案中增加切分点。"
        )
        return [int(hi)] * count, warning

    fixed: set[int] = set()
    for _ in range(count + 1):
        free = [i for i in range(count) if i not in fixed]
        budget = target - sum(values[i] for i in fixed)
        free_sum = sum(values[i] for i in free)
        if not free or free_sum <= 0:
            break
        factor = budget / free_sum
        changed = False
        for i in free:
            scaled = values[i] * factor
            if scaled < lo or scaled > hi:
                values[i] = min(max(scaled, lo), hi)
                fixed.add(i)
                changed = True
        if not changed:
            for i in free:
                values[i] = values[i] * factor
            break

    floors = [math.floor(x) for x in values]
    remainder = target - sum(floors)
    order = sorted(range(count), key=lambda i: values[i] - floors[i], reverse=True)
    for i in order:
        if remainder <= 0:
            break
        if floors[i] < hi:
            floors[i] += 1
            remainder -= 1
    return [min(max(x, int(lo)), int(hi)) for x in floors], warning


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def sanitize_blocking(
    raw: Any,
    *,
    script: dict[str, Any],
    target_duration_s: int | None,
    previous: dict[str, Any] | None = None,
    mode: SanitizeMode = "llm",
    reconcile_keys: set[str] | None = None,
) -> SanitizeResult:
    """Returns a complete, bounded document aligned with `script`.

    `mode="llm"`: segments present in `raw` are freshly staged, so they get
    the current `source_hash`; a manual `camera_override` carries over from
    `previous` only when the model left that segment's shot untouched.
    `mode="manual"`: `raw` is the browser's own full document — its
    overrides are kept and its hashes are trusted as echoes.

    Freshly staged segments have their shots reconciled with the script's
    camera blocks (`_reconcile_with_script`). `reconcile_keys` narrows that
    to the given keys — a staging-only chat turn passes just the segments
    whose script changed, so a camera change the author asked for in words
    is not overwritten by the script's older camera text.
    """
    raw = raw if isinstance(raw, dict) else {}
    previous = previous if isinstance(previous, dict) and previous.get("segments") else None
    segments_in_script = ordered_segments(script)[: v.MAX_SEGMENTS]

    target = (
        int(target_duration_s)
        if target_duration_s
        else default_target_duration(script) or v.SEGMENT_MIN_SECONDS
    )
    target = min(max(target, 1), v.TARGET_DURATION_MAX_SECONDS)

    sets = _sanitize_sets(raw, script=script, previous=previous)
    set_by_heading = {s["heading"]: s for s in sets}
    cast, aliases = _sanitize_cast(raw, script=script, previous=previous)

    raw_segments = _dicts(raw.get("segments"), v.MAX_SEGMENTS * 2)
    prev_segments = _dicts((previous or {}).get("segments"), v.MAX_SEGMENTS * 2)
    raw_by_key = {str(s.get("key") or ""): s for s in raw_segments}
    prev_by_key = {str(s.get("key") or ""): s for s in prev_segments}
    script_keys = {segment.key for segment in segments_in_script}
    positional_prev = len(prev_segments) == len(segments_in_script)

    chosen: list[tuple[ScriptSegment, dict[str, Any], str]] = []
    for index, segment in enumerate(segments_in_script):
        if segment.key in raw_by_key:
            chosen.append((segment, raw_by_key[segment.key], "raw"))
        elif segment.key in prev_by_key:
            chosen.append((segment, prev_by_key[segment.key], "previous"))
        elif positional_prev and str(prev_segments[index].get("key") or "") not in script_keys:
            chosen.append((segment, prev_segments[index], "previous"))
        else:
            chosen.append((segment, {}, "default"))

    raw_durations = [
        _num(source.get("duration_s"), 0.0, 0.0, 120.0) or estimate_segment_seconds(segment.blocks)
        for segment, source, _ in chosen
    ]
    durations, warning = fit_durations(raw_durations, target)

    segments: list[dict[str, Any]] = []
    for (segment, source, origin), duration in zip(chosen, durations, strict=True):
        set_ = set_by_heading.get(segment.heading) or _default_set("s0", segment.heading)
        staged = _sanitize_segment(
            source,
            segment=segment,
            set_=set_,
            cast=cast,
            aliases=aliases,
            duration=float(duration),
            # Freshly staged segments follow the script's camera blocks; a
            # manual edit or a carried-over segment keeps what it has.
            reconcile=(origin == "default" or (mode == "llm" and origin == "raw"))
            and (reconcile_keys is None or segment.key in reconcile_keys),
        )
        staged["duration_s"] = int(duration)
        fresh_hash = staged["source_hash"]
        echoed = str(source.get("source_hash") or "")
        if origin == "previous" or (mode == "manual" and origin == "raw"):
            # A segment kept from an earlier version is still staged from
            # the script as it stood then — keep that hash so the staleness
            # check keeps flagging it until someone re-stages it.
            staged["source_hash"] = echoed if _HASH16.match(echoed) else fresh_hash

        override: dict[str, Any] | None = None
        if (mode == "manual" and origin == "raw") or origin == "previous":
            override = _sanitize_override(source.get("camera_override"))
        elif origin == "raw" and previous is not None:
            before = prev_by_key.get(segment.key)
            if before is not None and before.get("camera_override"):
                before_shots = [
                    _sanitize_shot(
                        item,
                        cast_ids={e["cast_id"] for e in staged["start"]},
                        anchors={a["id"] for a in set_["anchors"]},
                        aliases=aliases,
                        fallback=staged["shots"][0],
                        duration=float(duration),
                    )
                    for item in _raw_shots(before)
                ]
                if _shot_signature(before_shots) == _shot_signature(staged["shots"]):
                    override = _sanitize_override(before.get("camera_override"))
        staged["camera_override"] = override
        segments.append(staged)

    aspect = _choice(
        raw.get("aspect_ratio") or (previous or {}).get("aspect_ratio"), v.ASPECT_RATIOS, "9:16"
    )
    document = {
        "version": BLOCKING_VERSION,
        "script_hash": script_hash(script),
        "target_duration_s": target,
        "aspect_ratio": aspect,
        "sets": sets,
        "cast": cast,
        "segments": segments,
    }
    return SanitizeResult(document=document, duration_warning=warning)


def stale_segment_keys(document: dict[str, Any], script: dict[str, Any]) -> list[str]:
    """Keys whose script content changed since they were staged, plus keys
    the script gained or lost — what the "rebuild" banner lists."""
    staged = {
        str(s.get("key")): str(s.get("source_hash") or "")
        for s in document.get("segments") or []
        if isinstance(s, dict)
    }
    current = {s.key: segment_source_hash(s) for s in ordered_segments(script)}
    stale = [key for key, digest in current.items() if staged.get(key) != digest]
    stale.extend(key for key in staged if key not in current)
    return stale
