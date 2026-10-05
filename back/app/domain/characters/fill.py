"""补齐缺失 (P2-4): what a character look is missing, and the jobs that make it.

A look's standard set is the card's identity portrait (定妆照, shared by every
look), the look's front sheet, four turnaround poses — right side 90°, back
180°, left side 270°, front-right 45° (AC-2; an old `side`/`back` view counts
as 90°/180°) — and one composite expression image. Only approved entries count: a slot that only has
candidates is reported as such and not regenerated — the owner approves or
deletes those first.

The jobs run in waves because each draws from the one before it:

1. the identity portrait (when missing);
2. the front sheet;
3. one multi-angle (`camera_poses`, `image_to_image`) job for the missing
   poses, drawn from the look's approved front single figure (a 0° view) —
   or from its approved sheet, in which case the job first draws that front
   figure (`camera_from_sheet`, `nodes._chain_orbit_front`). Planned only
   once the sheet is approved;
4. the expression image (needs a face to draw from).

`plan` recomputes everything from the card each time, so the next wave is
simply "the first group still missing": calling the fill endpoint again
after a wave finishes continues where it left off, and a user who left
half-way just presses 补齐缺失 again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters.service import CharacterView
from app.domain.image_assets import camera as camera_vocab
from app.domain.image_assets.vocabulary import MAX_CHARACTER_EXPRESSIONS
from app.models import SkillAssetEntry, SkillAssetVariant
from app.models.enums import AssetEntryType, CharacterViewAngle, ImageAssetKind, Operation

# Decided 2026-10-02: one 2×3 composite of six everyday expressions.
DEFAULT_FILL_EXPRESSIONS = ("neutral", "smile", "anger", "sad", "shock", "fear")

Slot = Literal["portrait", "front", "side", "back", "left", "three_quarter", "expressions"]
SLOTS: tuple[Slot, ...] = (
    "portrait",
    "front",
    "side",
    "back",
    "left",
    "three_quarter",
    "expressions",
)
SlotStatus = Literal["present", "candidate", "missing"]
# The turnaround poses, each its own slot (`asset_variants.slot_mates`).
ORBIT_SLOT_AZIMUTH: dict[Slot, int] = {"side": 90, "back": 180, "left": 270, "three_quarter": 45}


@dataclass(frozen=True, slots=True)
class FillLine:
    """One job of the plan."""

    wave: int
    slots: tuple[Slot, ...]
    params: dict[str, Any] = field(hash=False)
    operation: Operation = Operation.TEXT_TO_IMAGE

    @property
    def output_count(self) -> int:
        """Images the job is priced for (one per pose or view; one otherwise)."""
        poses = self.params.get("camera_poses")
        if isinstance(poses, list) and poses:
            return len(poses)
        views = self.params.get("character_views")
        return len(views) if isinstance(views, list) and views else 1


def _status(entries: list[SkillAssetEntry]) -> SlotStatus:
    if any(asset_variants_service.is_approved(e) for e in entries):
        return "present"
    return "candidate" if entries else "missing"


def gaps(character: CharacterView, look: SkillAssetVariant) -> dict[Slot, SlotStatus]:
    """Each slot of the look's standard set and what the card holds for it."""
    skill = character.skill
    portraits = [
        e
        for e in asset_variants_service.entries(skill)
        if e.entry_type == AssetEntryType.IDENTITY_PORTRAIT
    ]
    entries = list(look.entries)
    status: dict[Slot, SlotStatus] = {
        "portrait": _status(portraits),
        "front": _status([e for e in entries if e.entry_type == AssetEntryType.CHARACTER_SHEET]),
        "expressions": _status(
            [e for e in entries if e.entry_type == AssetEntryType.EXPRESSION_SHEET]
        ),
    }
    for slot, azimuth in ORBIT_SLOT_AZIMUTH.items():
        status[slot] = _status(_views_at(entries, azimuth))
    return {slot: status[slot] for slot in SLOTS}


def _views_at(entries: list[SkillAssetEntry], azimuth: int) -> list[SkillAssetEntry]:
    """Single views drawn from `azimuth` at eye level, any distance."""
    found: list[SkillAssetEntry] = []
    for entry in entries:
        if entry.entry_type != AssetEntryType.VIEW:
            continue
        pose = asset_variants_service.entry_pose(entry)
        if pose is not None and camera_vocab.snap(pose).azimuth == azimuth and pose.elevation == 0:
            found.append(entry)
    return found


def _orbit_source(look: SkillAssetVariant) -> tuple[SkillAssetEntry, bool] | None:
    """What the turnaround job draws from: the look's approved front single
    figure (`False`), else its approved sheet (`True` — the job draws the
    front figure first). `None` until either is approved."""
    approved = [e for e in look.entries if asset_variants_service.is_approved(e)]
    front_figure = next(iter(_views_at(approved, 0)), None)
    if front_figure is not None:
        return front_figure, False
    sheet = next((e for e in approved if e.entry_type == AssetEntryType.CHARACTER_SHEET), None)
    return (sheet, True) if sheet is not None else None


def _prompt(character: CharacterView, look: SkillAssetVariant, *, with_outfit: bool) -> str:
    """The card's name and appearance — plus the look's outfit for a sheet,
    the same text the library's "生成到此处" jump-out seeds."""
    parts = [character.name.strip()]
    if character.description:
        parts.append(character.description.strip().rstrip("。．."))
    if with_outfit and look.description and not look.is_default:
        parts.append(look.description.strip().rstrip("。．."))
    return "。".join(part for part in parts if part)


def plan(
    character: CharacterView,
    look: SkillAssetVariant,
    *,
    slots: list[Slot] | None = None,
    expressions: list[str] | None = None,
    aspect_ratio: str = "16:9",
) -> list[FillLine]:
    """The jobs that fill the look's missing slots (restricted to `slots`
    when given), in wave order. Empty when nothing is missing."""
    status = gaps(character, look)
    wanted = [slot for slot in SLOTS if slot in (slots or SLOTS) and status[slot] == "missing"]
    base: dict[str, Any] = {
        "aspect_ratio": aspect_ratio,
        "asset_kind": ImageAssetKind.CHARACTER.value,
        "target_character_id": character.id,
        "subject_name_hint": character.name[:60],
    }
    lines: list[FillLine] = []
    wave = 0
    if "portrait" in wanted:
        wave += 1
        lines.append(
            FillLine(
                wave=wave,
                slots=("portrait",),
                params={
                    **base,
                    "prompt": _prompt(character, look, with_outfit=False),
                    "character_portrait": True,
                },
            )
        )
    if "front" in wanted:
        wave += 1
        lines.append(
            FillLine(
                wave=wave,
                slots=("front",),
                params={
                    **base,
                    "prompt": _prompt(character, look, with_outfit=True),
                    "target_variant_id": look.id,
                    "character_views": [CharacterViewAngle.FRONT.value],
                },
            )
        )
    orbit_slots = [slot for slot in ORBIT_SLOT_AZIMUTH if slot in wanted]
    source = _orbit_source(look)
    # With the sheet still to come, the turnaround is priced now and gets its
    # source when it is the next wave (the plan is recomputed every call).
    pending_sheet = source is None and "front" in wanted
    if orbit_slots and (source is not None or pending_sheet):
        entry, from_sheet = source if source is not None else (None, True)
        poses = [camera_vocab.CameraPose(ORBIT_SLOT_AZIMUTH[slot]) for slot in orbit_slots]
        if from_sheet:
            poses = [camera_vocab.CameraPose(0), *poses]
        wave += 1
        lines.append(
            FillLine(
                wave=wave,
                slots=tuple(orbit_slots),
                params={
                    **base,
                    "aspect_ratio": "3:4",
                    "prompt": _prompt(character, look, with_outfit=True),
                    "target_variant_id": look.id,
                    "source_entry_id": entry.id if entry is not None else None,
                    "camera_poses": [pose.as_dict() for pose in poses],
                    "camera_from_sheet": from_sheet,
                },
                operation=Operation.IMAGE_TO_IMAGE,
            )
        )
    if "expressions" in wanted:
        wave += 1
        picked = list(dict.fromkeys(expressions or DEFAULT_FILL_EXPRESSIONS))
        lines.append(
            FillLine(
                wave=wave,
                slots=("expressions",),
                params={
                    **base,
                    "prompt": _prompt(character, look, with_outfit=True),
                    "target_variant_id": look.id,
                    "character_expressions": picked[:MAX_CHARACTER_EXPRESSIONS],
                },
            )
        )
    return lines
