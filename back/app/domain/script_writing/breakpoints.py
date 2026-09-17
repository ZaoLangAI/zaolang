"""Script breakpoint ordering, ported from the frontend's
`front/src/features/script/script-breakpoint.ts`.

A breakpoint key is `{heading}#{ordinal}`: the ordinal-th `breakpoint` block
of that scene. A scene whose last block is not a breakpoint but still has
shootable content after its last one gets a virtual closer keyed
`{heading}#{count}` (never persisted). A dialogue line is keyed
`{heading}#L{blockIndex}`. These are the keys `Draft.params_json
.link_breakpoint_key` stores, so the order and the keys here must match the
frontend exactly — `tests/unit/test_script_breakpoints.py` mirrors
`script-breakpoint.test.ts`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Segment:
    """One generation segment: the blocks `[start, end)` of one scene, closed
    by the breakpoint block at `end` (or by the scene's end, for a trailing
    closer)."""

    key: str
    scene_index: int
    heading: str
    start: int
    end: int


def breakpoint_key(heading: str, ordinal: int) -> str:
    return f"{heading}#{ordinal}"


def dialogue_line_key(heading: str, block_index: int) -> str:
    return f"{heading}#L{block_index}"


def scene_blocks(scene: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The scene's blocks as `Segment.start`/`end` index them."""
    return [block for block in scene.get("blocks") or [] if isinstance(block, Mapping)]


def _has_shootable_content(blocks: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        block.get("type") != "breakpoint" and str(block.get("text") or "").strip()
        for block in blocks
    )


def ordered_segments(script: Mapping[str, Any]) -> list[Segment]:
    """Every breakpoint in shoot order — scene order, then each scene's own
    breakpoints by ordinal, then its trailing closer if it has one."""
    segments: list[Segment] = []
    for scene_index, scene in enumerate(script.get("scenes") or []):
        if not isinstance(scene, Mapping):
            continue
        heading = str(scene.get("heading") or "")
        blocks = scene_blocks(scene)
        ordinal = 0
        start = 0
        for index, block in enumerate(blocks):
            if block.get("type") != "breakpoint":
                continue
            segments.append(
                Segment(breakpoint_key(heading, ordinal), scene_index, heading, start, index)
            )
            ordinal += 1
            start = index + 1
        if (
            blocks
            and blocks[-1].get("type") != "breakpoint"
            and _has_shootable_content(blocks[start:])
        ):
            segments.append(
                Segment(breakpoint_key(heading, ordinal), scene_index, heading, start, len(blocks))
            )
    return segments


def ordered_breakpoint_keys(script: Mapping[str, Any]) -> list[str]:
    return [segment.key for segment in ordered_segments(script)]


def segment_containing(
    segments: Sequence[Segment], scene_index: int, block_index: int
) -> Segment | None:
    """The segment a block belongs to (a dialogue line's, for placing its
    voice clip), or `None` for a block after the last breakpoint of a scene
    with no trailing closer."""
    for segment in segments:
        if segment.scene_index == scene_index and segment.start <= block_index < segment.end:
            return segment
    return None
