"""Canonical EditCommand batches: failed commands never mutate the document."""

from __future__ import annotations

import pytest

from app.domain.editor import commands
from app.domain.editor import document as docs
from app.domain.errors import BatchRolledBack, ValidationFailed


def test_a_failed_batch_leaves_the_document_unchanged() -> None:
    document = docs.empty_document()
    original = docs.clone_document(document)
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [
                {
                    "type": "insert_clip",
                    "track_id": "trk_video",
                    "asset_id": "ast_ok",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                },
                {
                    "type": "insert_clip",
                    "track_id": "trk_missing",
                    "asset_id": "ast_ok",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                },
            ],
            known_assets={"ast_ok"},
        )
    assert document == original


def test_insert_then_trim_is_applied_atomically() -> None:
    document = docs.empty_document()
    result = commands.apply_batch(
        document,
        [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 240_000,
                "element_id": "el_clip",
            },
            {
                "type": "trim_element",
                "element_id": "el_clip",
                "start_ticks": 0,
                "duration_ticks": 120_000,
                "source_in_ticks": 0,
                "source_out_ticks": 120_000,
            },
        ],
        known_assets={"ast_ok"},
    )
    clip = docs.find_element(result, "el_clip")
    assert clip is not None
    assert clip[1]["duration_ticks"] == 120_000
    assert docs.duration_ticks(result) == 120_000


def test_generic_path_updates_are_rejected() -> None:
    with pytest.raises(ValidationFailed):
        commands.validate_batch(
            {
                "schema_version": 1,
                "batch_id": "bat_1",
                "commands": [{"type": "update_property", "path": "tracks.0", "value": 1}],
            }
        )


def test_ticks_must_be_safe_integers() -> None:
    with pytest.raises(ValidationFailed):
        commands.validate_batch(
            {
                "schema_version": 1,
                "batch_id": "bat_1",
                "commands": [
                    {
                        "type": "insert_clip",
                        "track_id": "trk_video",
                        "asset_id": "ast_ok",
                        "at_ticks": 1.5,
                        "duration_ticks": 120_000,
                    }
                ],
            }
        )


def test_add_track_then_insert_clip_onto_it_in_one_batch() -> None:
    document = docs.empty_document()
    result = commands.apply_batch(
        document,
        [
            {"type": "add_track", "kind": "video", "track_id": "trk_pip", "label": "画中画"},
            {
                "type": "insert_clip",
                "track_id": "trk_pip",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 120_000,
            },
        ],
        known_assets={"ast_ok"},
    )
    track = docs.find_track(result, "trk_pip")
    assert track is not None
    assert track["kind"] == "video"
    assert track["label"] == "画中画"
    assert len(track["elements"]) == 1


def test_add_track_rejects_caption_or_overlay_kind() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(), [{"type": "add_track", "kind": "caption"}], known_assets=set()
        )


def test_add_track_rejects_over_the_per_kind_cap() -> None:
    document = docs.empty_document()
    from app.domain.editor.time import MAX_TRACKS_PER_KIND

    batch = [{"type": "add_track", "kind": "audio"} for _ in range(MAX_TRACKS_PER_KIND)]
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(document, batch, known_assets=set())


def test_remove_track_rejects_the_last_track_of_a_kind() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(),
            [{"type": "remove_track", "track_id": "trk_video"}],
            known_assets=set(),
        )


def test_remove_track_rejects_a_non_empty_track() -> None:
    document = docs.empty_document()
    document = commands.apply_batch(
        document,
        [
            {"type": "add_track", "kind": "video", "track_id": "trk_extra"},
            {
                "type": "insert_clip",
                "track_id": "trk_extra",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 120_000,
            },
        ],
        known_assets={"ast_ok"},
    )
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document, [{"type": "remove_track", "track_id": "trk_extra"}], known_assets=set()
        )


def test_remove_track_rejects_caption_and_overlay() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(),
            [{"type": "remove_track", "track_id": "trk_caption"}],
            known_assets=set(),
        )


def test_remove_track_then_re_add_succeeds_when_empty() -> None:
    document = docs.empty_document()
    document = commands.apply_batch(
        document, [{"type": "add_track", "kind": "video", "track_id": "trk_extra"}], known_assets=set()
    )
    result = commands.apply_batch(
        document, [{"type": "remove_track", "track_id": "trk_extra"}], known_assets=set()
    )
    assert docs.find_track(result, "trk_extra") is None
    # `trk_video` must survive — only the extra track is gone.
    assert docs.find_track(result, "trk_video") is not None


def test_set_track_order_changes_canonicalized_order() -> None:
    document = docs.empty_document()
    document = commands.apply_batch(
        document, [{"type": "add_track", "kind": "video", "track_id": "trk_top"}], known_assets=set()
    )
    document = commands.apply_batch(
        document,
        [{"type": "set_track_order", "track_id": "trk_top", "order": -1}],
        known_assets=set(),
    )
    canonical = docs.canonicalize(document)
    video_tracks = [t for t in canonical["tracks"] if t["kind"] == "video"]
    assert video_tracks[0]["id"] == "trk_top"


def test_set_track_muted_toggles_flag() -> None:
    document = docs.empty_document()
    result = commands.apply_batch(
        document, [{"type": "set_track_muted", "track_id": "trk_audio", "muted": True}], known_assets=set()
    )
    track = docs.find_track(result, "trk_audio")
    assert track is not None
    assert track["muted"] is True


def test_insert_clip_rejects_a_mismatched_track_kind() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(),
            [
                {
                    "type": "insert_clip",
                    "track_id": "trk_caption",
                    "asset_id": "ast_ok",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                }
            ],
            known_assets={"ast_ok"},
        )


def test_insert_caption_rejects_a_mismatched_track_kind() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(),
            [
                {
                    "type": "insert_caption",
                    "track_id": "trk_video",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "text": "hi",
                }
            ],
            known_assets=set(),
        )


def test_move_elements_rejects_moving_across_track_kinds() -> None:
    document = docs.empty_document()
    document = commands.apply_batch(
        document,
        [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 120_000,
                "element_id": "el_clip",
            }
        ],
        known_assets={"ast_ok"},
    )
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [
                {
                    "type": "move_elements",
                    "element_ids": ["el_clip"],
                    "delta_ticks": 0,
                    "track_id": "trk_audio",
                }
            ],
            known_assets=set(),
        )


def _document_with_clip() -> dict:
    return commands.apply_batch(
        docs.empty_document(),
        [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 4 * 120_000,
                "element_id": "el_clip",
            }
        ],
        known_assets={"ast_ok"},
    )


def _clip(document: dict) -> dict:
    return next(el for el in document["tracks"][0]["elements"] if el["id"] == "el_clip")


def test_add_effect_appends_and_rejects_unknown_type() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "add_effect", "element_id": "el_clip", "effect": {"type": "blur", "params": {"intensity": 20}}},
            {
                "type": "add_effect",
                "element_id": "el_clip",
                "effect": {"type": "grayscale", "params": {"amount": 100}},
            },
        ],
        known_assets=set(),
    )
    assert _clip(document)["effects"] == [
        {"type": "blur", "params": {"intensity": 20}},
        {"type": "grayscale", "params": {"amount": 100}},
    ]
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [{"type": "add_effect", "element_id": "el_clip", "effect": {"type": "sepia", "params": {}}}],
            known_assets=set(),
        )


def test_add_effect_caps_effects_per_element() -> None:
    document = _document_with_clip()
    batch = [
        {"type": "add_effect", "element_id": "el_clip", "effect": {"type": "brightness", "params": {"amount": 110}}}
        for _ in range(9)
    ]
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(document, batch, known_assets=set())


def test_remove_effect_by_index() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "add_effect", "element_id": "el_clip", "effect": {"type": "blur", "params": {"intensity": 20}}},
            {"type": "add_effect", "element_id": "el_clip", "effect": {"type": "contrast", "params": {"amount": 120}}},
        ],
        known_assets=set(),
    )
    document = commands.apply_batch(
        document, [{"type": "remove_effect", "element_id": "el_clip", "effect_index": 0}], known_assets=set()
    )
    assert _clip(document)["effects"] == [{"type": "contrast", "params": {"amount": 120}}]
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document, [{"type": "remove_effect", "element_id": "el_clip", "effect_index": 5}], known_assets=set()
        )


def test_update_effect_params_merges_without_dropping_keys() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {
                "type": "add_effect",
                "element_id": "el_clip",
                "effect": {"type": "blur", "params": {"intensity": 20, "extra": 1}},
            }
        ],
        known_assets=set(),
    )
    document = commands.apply_batch(
        document,
        [{"type": "update_effect_params", "element_id": "el_clip", "effect_index": 0, "params": {"intensity": 40}}],
        known_assets=set(),
    )
    assert _clip(document)["effects"][0]["params"] == {"intensity": 40, "extra": 1}


def test_set_clip_mask_sets_and_clears() -> None:
    mask = {
        "shape": "ellipse",
        "x_milli": 100,
        "y_milli": 100,
        "width_milli": 800,
        "height_milli": 800,
        "feather_millipercent": 10_000,
    }
    document = commands.apply_batch(
        _document_with_clip(),
        [{"type": "set_clip_mask", "element_id": "el_clip", "mask": mask}],
        known_assets=set(),
    )
    assert _clip(document)["mask"] == mask
    document = commands.apply_batch(
        document, [{"type": "set_clip_mask", "element_id": "el_clip", "mask": None}], known_assets=set()
    )
    assert _clip(document)["mask"] is None


def test_set_clip_mask_rejects_unsupported_shape() -> None:
    document = _document_with_clip()
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [
                {
                    "type": "set_clip_mask",
                    "element_id": "el_clip",
                    "mask": {
                        "shape": "star",
                        "x_milli": 0,
                        "y_milli": 0,
                        "width_milli": 100,
                        "height_milli": 100,
                        "feather_millipercent": 0,
                    },
                }
            ],
            known_assets=set(),
        )


def test_split_element_does_not_alias_effects_between_halves() -> None:
    """Regression: a shallow `dict(element)` copy in `_split_element` used to
    share the same `effects` list object with the original — an
    add_effect/remove_effect on one half then silently mutated the other."""
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "add_effect", "element_id": "el_clip", "effect": {"type": "blur", "params": {"intensity": 20}}},
            {"type": "split_element", "element_id": "el_clip", "at_ticks": 2 * 120_000},
        ],
        known_assets=set(),
    )
    elements = document["tracks"][0]["elements"]
    left = next(el for el in elements if el["id"] == "el_clip")
    right = next(el for el in elements if el["id"] != "el_clip")
    assert left["effects"] == right["effects"] == [{"type": "blur", "params": {"intensity": 20}}]

    document = commands.apply_batch(
        document,
        [{"type": "add_effect", "element_id": right["id"], "effect": {"type": "grayscale", "params": {"amount": 100}}}],
        known_assets=set(),
    )
    elements = document["tracks"][0]["elements"]
    left = next(el for el in elements if el["id"] == "el_clip")
    right = next(el for el in elements if el["id"] != "el_clip")
    assert len(left["effects"]) == 1, "the left half must not pick up the right half's new effect"
    assert len(right["effects"]) == 2


def test_set_keyframe_inserts_sorted_and_replaces_same_tick() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 2 * 120_000, "value": 100_000},
            {"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 0},
        ],
        known_assets=set(),
    )
    points = _clip(document)["animations"]["channels"]["opacity"]["points"]
    assert [p["at_ticks"] for p in points] == [0, 2 * 120_000]

    document = commands.apply_batch(
        document,
        [{"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 90_000}],
        known_assets=set(),
    )
    points = _clip(document)["animations"]["channels"]["opacity"]["points"]
    assert points == [{"at_ticks": 0, "value": 90_000}, {"at_ticks": 2 * 120_000, "value": 100_000}]


def test_set_keyframe_rejects_unknown_property_and_out_of_range_value() -> None:
    document = _document_with_clip()
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [{"type": "set_keyframe", "element_id": "el_clip", "property": "color", "at_ticks": 0, "value": 0}],
            known_assets=set(),
        )
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [{"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 999_999}],
            known_assets=set(),
        )


def test_delete_keyframe_removes_exact_tick_and_rejects_missing() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [{"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 50_000}],
        known_assets=set(),
    )
    document = commands.apply_batch(
        document,
        [{"type": "delete_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0}],
        known_assets=set(),
    )
    assert _clip(document)["animations"]["channels"]["opacity"]["points"] == []
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [{"type": "delete_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0}],
            known_assets=set(),
        )


def test_clear_keyframes_removes_the_whole_channel() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 0},
            {"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 1000, "value": 100_000},
        ],
        known_assets=set(),
    )
    document = commands.apply_batch(
        document, [{"type": "clear_keyframes", "element_id": "el_clip", "property": "opacity"}], known_assets=set()
    )
    assert "opacity" not in _clip(document)["animations"]["channels"]


def test_split_element_does_not_alias_keyframe_channels_between_halves() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {"type": "set_keyframe", "element_id": "el_clip", "property": "opacity", "at_ticks": 0, "value": 50_000},
            {"type": "split_element", "element_id": "el_clip", "at_ticks": 2 * 120_000},
        ],
        known_assets=set(),
    )
    elements = document["tracks"][0]["elements"]
    right = next(el for el in elements if el["id"] != "el_clip")
    document = commands.apply_batch(
        document,
        [{"type": "set_keyframe", "element_id": right["id"], "property": "opacity", "at_ticks": 500, "value": 20_000}],
        known_assets=set(),
    )
    left = next(el for el in document["tracks"][0]["elements"] if el["id"] == "el_clip")
    assert len(left["animations"]["channels"]["opacity"]["points"]) == 1, (
        "the left half must not pick up the right half's new keyframe"
    )


def test_insert_clip_element_type_defaults_to_clip_and_supports_sticker() -> None:
    document = commands.apply_batch(
        docs.empty_document(),
        [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": "ast_ok",
                "at_ticks": 0,
                "duration_ticks": 120_000,
                "element_id": "el_plain",
            },
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": "ast_ok",
                "at_ticks": 120_000,
                "duration_ticks": 120_000,
                "element_id": "el_sticker",
                "element_type": "sticker",
            },
        ],
        known_assets={"ast_ok"},
    )
    elements = {el["id"]: el for el in document["tracks"][0]["elements"]}
    assert elements["el_plain"]["type"] == "clip"
    assert elements["el_sticker"]["type"] == "sticker"


def test_insert_clip_rejects_an_unsupported_element_type() -> None:
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            docs.empty_document(),
            [
                {
                    "type": "insert_clip",
                    "track_id": "trk_video",
                    "asset_id": "ast_ok",
                    "at_ticks": 0,
                    "duration_ticks": 120_000,
                    "element_type": "shape",
                }
            ],
            known_assets={"ast_ok"},
        )


def test_set_transition_sets_each_edge_independently_and_clears_with_null() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {
                "type": "set_transition",
                "element_id": "el_clip",
                "edge": "out",
                "transition": {"type": "crossfade", "duration_ticks": 120_000},
            }
        ],
        known_assets=set(),
    )
    element = _clip(document)
    assert element["transition_out"] == {"type": "crossfade", "duration_ticks": 120_000}
    assert element["transition_in"] is None

    document = commands.apply_batch(
        document,
        [{"type": "set_transition", "element_id": "el_clip", "edge": "out", "transition": None}],
        known_assets=set(),
    )
    assert _clip(document)["transition_out"] is None


def test_set_transition_rejects_unsupported_type_and_oversized_duration() -> None:
    document = _document_with_clip()  # duration = 4 * 120_000
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [
                {
                    "type": "set_transition",
                    "element_id": "el_clip",
                    "edge": "out",
                    "transition": {"type": "wipe", "duration_ticks": 120_000},
                }
            ],
            known_assets=set(),
        )
    with pytest.raises(BatchRolledBack):
        commands.apply_batch(
            document,
            [
                {
                    "type": "set_transition",
                    "element_id": "el_clip",
                    "edge": "out",
                    "transition": {"type": "crossfade", "duration_ticks": 10 * 120_000},
                }
            ],
            known_assets=set(),
        )


def test_split_element_moves_transition_out_to_the_right_half() -> None:
    document = commands.apply_batch(
        _document_with_clip(),
        [
            {
                "type": "set_transition",
                "element_id": "el_clip",
                "edge": "in",
                "transition": {"type": "crossfade", "duration_ticks": 120_000},
            },
            {
                "type": "set_transition",
                "element_id": "el_clip",
                "edge": "out",
                "transition": {"type": "dip_to_black", "duration_ticks": 120_000},
            },
            {"type": "split_element", "element_id": "el_clip", "at_ticks": 2 * 120_000},
        ],
        known_assets=set(),
    )
    elements = document["tracks"][0]["elements"]
    left = next(el for el in elements if el["id"] == "el_clip")
    right = next(el for el in elements if el["id"] != "el_clip")
    assert left["transition_in"] == {"type": "crossfade", "duration_ticks": 120_000}
    assert left["transition_out"] is None
    assert right["transition_in"] is None
    assert right["transition_out"] == {"type": "dip_to_black", "duration_ticks": 120_000}


def test_planner_prompt_mentions_every_allowed_command_type() -> None:
    """Guards against the 3-way manual sync silently drifting.

    A new `EditCommand` type added to `commands.ALLOWED_TYPES` without also
    updating `editor_planner.SYSTEM_PROMPT` becomes invisible to the AI
    planner with no error anywhere — it just never gets emitted. This test
    turns that into a loud, immediate failure instead.
    """
    from app.agents.editor_planner import SYSTEM_PROMPT

    missing = {
        command_type for command_type in commands.ALLOWED_TYPES if command_type not in SYSTEM_PROMPT
    }
    assert not missing, f"editor_planner.SYSTEM_PROMPT is missing: {sorted(missing)}"
