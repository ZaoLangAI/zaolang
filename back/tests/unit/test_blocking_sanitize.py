"""`app.domain.blocking.sanitize` — the one validator between a model (or a
browser) and `DramaEpisode.blocking_json`."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.domain.blocking.sanitize import fit_durations, sanitize_blocking, stale_segment_keys
from app.domain.blocking.segments import ordered_segments, segment_source_hash


def _script() -> dict[str, Any]:
    return {
        "title": "t",
        "logline": "",
        "characters": [
            {"name": "林夏", "traits": "", "character_ref_id": "chr_lin"},
            {"name": "陈默", "traits": "", "character_ref_id": None},
        ],
        "scenes": [
            {
                "heading": "便利店 - 夜",
                "ref_id": None,
                "blocks": [
                    {"type": "dialogue", "character": "林夏", "text": "你来了。"},
                    {"type": "breakpoint", "character": None, "text": "cut"},
                    {"type": "action", "character": None, "text": "陈默推门进来"},
                ],
            },
            {
                "heading": "天台 - 夜",
                "ref_id": None,
                "blocks": [{"type": "camera", "character": None, "text": "远景，缓慢推近"}],
            },
        ],
    }


def _reply() -> dict[str, Any]:
    return {
        "aspect_ratio": "16:9",
        "sets": [
            {
                "heading": "便利店 - 夜",
                "ground": "floor",
                "width_m": 8,
                "depth_m": 6,
                "props": [
                    {
                        "id": "counter",
                        "primitive": "box",
                        "label": "柜台",
                        "color_role": "furniture",
                        "position": [0, 0.5, -1.5],
                        "rotation_y_deg": 0,
                        "scale": [2.4, 1.0, 0.6],
                    }
                ],
                "anchors": [{"id": "door", "label": "门口", "x": 3, "z": 2}],
            }
        ],
        "cast": [
            {"id": "lin", "name": "林夏", "height_m": 1.65},
            {"id": "chen", "name": "陈默", "height_m": 1.8},
            {"id": "ghost", "name": "不存在", "height_m": 1.7},
        ],
        "segments": [
            {
                "key": "便利店 - 夜#0",
                "duration_s": 6,
                "start": {"lin": {"at": "door", "face": "chen", "action": "stand"}},
                "beats": [
                    {"cast_id": "林夏", "t0": 1, "t1": 4, "action": "walk", "to": [0, -2]},
                    {"cast_id": "ghost", "t0": 1, "t1": 2, "action": "wave"},
                ],
                "shot": {
                    "size": "close",
                    "lens_mm": 85,
                    "height": "eye",
                    "side": "ots_left",
                    "subject": "lin",
                    "over": "chen",
                    "move": {"preset": "push_in", "intensity": 0.3, "ease": "in_out"},
                },
            }
        ],
    }


def test_sets_cast_and_segments_are_forced_to_the_script() -> None:
    result = sanitize_blocking(_reply(), script=_script(), target_duration_s=None)
    doc = result.document

    assert [s["heading"] for s in doc["sets"]] == ["便利店 - 夜", "天台 - 夜"]
    # The heading the reply skipped still gets a (default) set.
    assert doc["sets"][1]["props"] == []
    assert [c["name"] for c in doc["cast"]] == ["林夏", "陈默"]
    # Links come from the script, never from the model.
    assert doc["cast"][0]["character_ref_id"] == "chr_lin"
    assert [s["key"] for s in doc["segments"]] == [s.key for s in ordered_segments(_script())]
    assert doc["aspect_ratio"] == "16:9"


def test_references_resolve_by_id_or_name_and_unknown_cast_is_dropped() -> None:
    doc = sanitize_blocking(_reply(), script=_script(), target_duration_s=None).document
    first = doc["segments"][0]
    assert first["start"][0]["cast_id"] == "lin"
    assert first["start"][0]["at"] == {"anchor": "door", "x": 3.0, "z": 2.0}
    assert first["start"][0]["face"] == {"target": "chen", "deg": 0.0}
    assert [b["cast_id"] for b in first["beats"]] == ["lin"]
    assert first["beats"][0]["to"] == {"anchor": None, "x": 0.0, "z": -2.0}


def test_over_the_shoulder_needs_an_on_set_over_character() -> None:
    # `chen` is not in this segment's `start`, so the OTS falls back to front.
    doc = sanitize_blocking(_reply(), script=_script(), target_duration_s=None).document
    shot = doc["segments"][0]["shot"]
    assert shot["side"] == "front"
    assert shot["over"] is None


def test_missing_segments_get_default_staging_from_the_script() -> None:
    doc = sanitize_blocking(_reply(), script=_script(), target_duration_s=None).document
    second = doc["segments"][1]
    # "陈默推门进来" mentions 陈默, so the default staging puts him on set.
    assert [e["cast_id"] for e in second["start"]] == ["chen"]
    assert second["shot"]["move"]["preset"] == "static"


def test_numbers_and_vocabulary_are_clamped() -> None:
    reply = _reply()
    reply["sets"][0]["width_m"] = 999
    reply["sets"][0]["props"][0]["position"] = [100, -5, 0]
    reply["sets"][0]["props"][0]["primitive"] = "teapot"
    reply["segments"][0]["shot"]["lens_mm"] = 1000
    reply["segments"][0]["shot"]["move"]["preset"] = "dolly_zoom"
    doc = sanitize_blocking(reply, script=_script(), target_duration_s=None).document
    set_ = doc["sets"][0]
    assert set_["width_m"] == 60.0
    assert set_["props"][0]["primitive"] == "box"
    assert set_["props"][0]["position"] == [30.0, 0.0, 0.0]
    shot = doc["segments"][0]["shot"]
    assert shot["lens_mm"] == 135
    assert shot["move"]["preset"] == "static"


def test_durations_fit_the_target_and_beats_rescale() -> None:
    result = sanitize_blocking(_reply(), script=_script(), target_duration_s=24)
    durations = [s["duration_s"] for s in result.document["segments"]]
    assert sum(durations) == 24
    assert all(5 <= d <= 15 for d in durations)
    first = result.document["segments"][0]
    scale = first["duration_s"] / 6
    assert first["beats"][0]["t0"] == pytest.approx(1 * scale, abs=0.01)
    assert result.duration_warning is None


def test_impossible_target_is_reported_not_silently_ignored() -> None:
    result = sanitize_blocking(_reply(), script=_script(), target_duration_s=4)
    assert all(s["duration_s"] == 5 for s in result.document["segments"])
    assert result.duration_warning


def test_fit_durations_rounds_with_the_largest_remainder() -> None:
    durations, warning = fit_durations([6.0, 6.0, 6.0], 20)
    assert sum(durations) == 20
    assert warning is None
    durations, _ = fit_durations([5.0, 30.0], 20)
    assert durations == [5, 15]


def test_partial_reply_is_completed_from_the_previous_version() -> None:
    first = sanitize_blocking(_reply(), script=_script(), target_duration_s=None).document
    partial = {"segments": [{**_reply()["segments"][0], "key": "天台 - 夜#0"}]}
    second = sanitize_blocking(
        partial, script=_script(), target_duration_s=None, previous=first
    ).document
    assert second["sets"][0]["props"] == first["sets"][0]["props"]
    assert second["segments"][0]["start"] == first["segments"][0]["start"]
    assert second["cast"] == first["cast"]


def test_camera_override_survives_only_when_the_shot_is_unchanged() -> None:
    first = sanitize_blocking(_reply(), script=_script(), target_duration_s=None).document
    override = {
        "start": {"position": [1, 1.6, 4], "target": [0, 1.2, 0], "fov": 35},
        "end": None,
    }
    manual = deepcopy(first)
    manual["segments"][0]["camera_override"] = override
    kept = sanitize_blocking(
        manual, script=_script(), target_duration_s=None, previous=first, mode="manual"
    ).document
    assert kept["segments"][0]["camera_override"]["start"]["fov"] == 35.0

    same_shot = sanitize_blocking(
        {"segments": [_reply()["segments"][0]]},
        script=_script(),
        target_duration_s=None,
        previous=kept,
    ).document
    assert same_shot["segments"][0]["camera_override"] is not None

    reshot = deepcopy(_reply()["segments"][0])
    reshot["shot"]["size"] = "wide"
    changed = sanitize_blocking(
        {"segments": [reshot]}, script=_script(), target_duration_s=None, previous=kept
    ).document
    assert changed["segments"][0]["camera_override"] is None


def test_llm_mode_ignores_overrides_in_the_reply() -> None:
    reply = _reply()
    reply["segments"][0]["camera_override"] = {
        "start": {"position": [0, 0, 0], "target": [0, 0, 0], "fov": 20}
    }
    doc = sanitize_blocking(reply, script=_script(), target_duration_s=None).document
    assert doc["segments"][0]["camera_override"] is None


def test_staleness_tracks_script_edits_per_segment() -> None:
    script = _script()
    doc = sanitize_blocking(_reply(), script=script, target_duration_s=None).document
    assert stale_segment_keys(doc, script) == []

    edited = deepcopy(script)
    edited["scenes"][1]["blocks"][0]["text"] = "特写，固定"
    assert stale_segment_keys(doc, edited) == ["天台 - 夜#0"]

    # Keeping a segment from the previous version keeps its old hash, so it
    # stays flagged until something re-stages it.
    carried = sanitize_blocking({}, script=edited, target_duration_s=None, previous=doc).document
    assert stale_segment_keys(carried, edited) == ["天台 - 夜#0"]
    restaged = sanitize_blocking(
        {"segments": [{"key": "天台 - 夜#0"}]}, script=edited, target_duration_s=None, previous=doc
    ).document
    assert stale_segment_keys(restaged, edited) == []
    assert restaged["segments"][2]["source_hash"] == segment_source_hash(
        ordered_segments(edited)[2]
    )


def test_heading_rename_keeps_the_set_and_segment_positionally() -> None:
    script = _script()
    doc = sanitize_blocking(_reply(), script=script, target_duration_s=None).document
    renamed = deepcopy(script)
    renamed["scenes"][0]["heading"] = "便利店 - 深夜"
    moved = sanitize_blocking({}, script=renamed, target_duration_s=None, previous=doc).document
    assert moved["sets"][0]["heading"] == "便利店 - 深夜"
    assert moved["sets"][0]["props"] == doc["sets"][0]["props"]
    assert moved["segments"][0]["key"] == "便利店 - 深夜#0"
    assert moved["segments"][0]["shot"] == doc["segments"][0]["shot"]


def test_garbage_input_still_yields_a_complete_document() -> None:
    doc = sanitize_blocking("not json", script=_script(), target_duration_s=30).document
    assert len(doc["segments"]) == 3
    assert sum(s["duration_s"] for s in doc["segments"]) == 30
    assert doc["aspect_ratio"] == "9:16"
