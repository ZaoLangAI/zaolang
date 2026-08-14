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
