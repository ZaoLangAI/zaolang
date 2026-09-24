"""Script segment keying, duration estimates and content hashes.

`ordered_segments` is the Python port of the frontend's
`orderedBreakpointKeys`/`breakpointSegmentBlocks`
(`front/src/features/script/script-breakpoint.ts`): the `{heading}#{ordinal}`
keys both sides use to bind one generated clip — and now one blocking
segment — to one stretch of script. The two implementations must agree key
for key; `tests/unit/test_blocking_segments.py` pins the shared cases.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.domain.blocking.vocabulary import SEGMENT_MAX_SECONDS, SEGMENT_MIN_SECONDS


@dataclass(frozen=True, slots=True)
class ScriptSegment:
    key: str
    heading: str
    scene_index: int
    blocks: tuple[dict[str, Any], ...]


def breakpoint_key(heading: str, ordinal: int) -> str:
    return f"{heading}#{ordinal}"


def _shootable(blocks: list[dict[str, Any]]) -> bool:
    return any(
        block.get("type") != "breakpoint" and str(block.get("text") or "").strip()
        for block in blocks
    )


def ordered_segments(script: dict[str, Any]) -> list[ScriptSegment]:
    """Every segment in generation order: scene order, then each scene's
    breakpoints by ordinal, then its unclosed tail (if it has content)."""
    segments: list[ScriptSegment] = []
    for scene_index, scene in enumerate(script.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        heading = str(scene.get("heading") or "")
        blocks = [b for b in scene.get("blocks") or [] if isinstance(b, dict)]
        ordinal = 0
        start = 0
        for index, block in enumerate(blocks):
            if block.get("type") != "breakpoint":
                continue
            segments.append(
                ScriptSegment(
                    key=breakpoint_key(heading, ordinal),
                    heading=heading,
                    scene_index=scene_index,
                    blocks=tuple(blocks[start:index]),
                )
            )
            ordinal += 1
            start = index + 1
        tail = blocks[start:]
        if blocks and blocks[-1].get("type") != "breakpoint" and _shootable(tail):
            segments.append(
                ScriptSegment(
                    key=breakpoint_key(heading, ordinal),
                    heading=heading,
                    scene_index=scene_index,
                    blocks=tuple(tail),
                )
            )
    return segments


# Same baselines `copywriter._BREAKPOINT_RULES` tells the model to reason
# with, so the default target duration agrees with how the script itself
# was split: Chinese dialogue at ~3.5 chars/s, a counted action beat ~3s,
# and a shot-size floor when a segment is mostly camera/scene description.
_DIALOGUE_CHARS_PER_SECOND = 3.5
_ACTION_BEAT_SECONDS = 3.0
_SHOT_SIZE_BASELINES: tuple[tuple[str, float], ...] = (
    ("大远景", 10.0),
    ("远景", 10.0),
    ("全景", 8.0),
    ("中近景", 5.0),
    ("中景", 6.0),
    ("大特写", 4.0),
    ("特写", 4.0),
    ("近景", 4.0),
)
_SPOKEN = re.compile(r"[（(][^）)]*[）)]")


def estimate_segment_seconds(blocks: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> float:
    spoken = 0.0
    actions = 0.0
    shot_floor = 0.0
    for block in blocks:
        kind = block.get("type")
        text = str(block.get("text") or "")
        if kind == "dialogue":
            line = _SPOKEN.sub("", text).strip()
            spoken += len(line) / _DIALOGUE_CHARS_PER_SECOND
        elif kind == "action":
            actions += _ACTION_BEAT_SECONDS
        elif kind == "camera":
            for marker, seconds in _SHOT_SIZE_BASELINES:
                if marker in text:
                    shot_floor = max(shot_floor, seconds)
                    break
    estimate = max(spoken + actions, shot_floor) or 6.0
    return float(min(max(estimate, SEGMENT_MIN_SECONDS), SEGMENT_MAX_SECONDS))


def default_target_duration(script: dict[str, Any]) -> int:
    return round(sum(estimate_segment_seconds(s.blocks) for s in ordered_segments(script)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _block_fingerprint(block: dict[str, Any]) -> list[Any]:
    return [block.get("type"), block.get("character"), str(block.get("text") or "")]


def segment_source_hash(segment: ScriptSegment) -> str:
    """What a blocking segment was staged from. Changes when the segment's
    own blocks change; ignores links, traits, title and logline."""
    return _digest([segment.heading, [_block_fingerprint(b) for b in segment.blocks]])[:16]


def script_hash(script: dict[str, Any]) -> str:
    """Whole-script fingerprint for the staleness banner — cast names plus
    every segment's content, nothing a blockout cannot show."""
    names = sorted(
        str(c.get("name") or "") for c in script.get("characters") or [] if isinstance(c, dict)
    )
    return _digest([names, [segment_source_hash(s) for s in ordered_segments(script)]])[:32]
