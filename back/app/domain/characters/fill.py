"""补齐缺失 (P2-4): what a character look is missing, and the jobs that make it.

A look's standard set is the card's identity portrait (定妆照, shared by every
look), the look's front sheet, its side and back views, and one composite
expression image. Only approved entries count: a slot that only has
candidates is reported as such and not regenerated — the owner approves or
deletes those first.

The jobs run in waves because each draws from the one before it:

1. the identity portrait (when missing);
2. one multi-view job for the missing front / side / back — its side and
   back passes reference this job's own front sheet
   (`workflows.nodes._chain_front_reference`), or the look's existing one
   (`reference_resolver`);
3. the expression image (needs a face to draw from).

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
from app.domain.image_assets.vocabulary import MAX_CHARACTER_EXPRESSIONS
from app.models import SkillAssetEntry, SkillAssetVariant
from app.models.enums import AssetEntryType, CharacterViewAngle, ImageAssetKind

# Decided 2026-10-02: one 2×3 composite of six everyday expressions.
DEFAULT_FILL_EXPRESSIONS = ("neutral", "smile", "anger", "sad", "shock", "fear")

Slot = Literal["portrait", "front", "side", "back", "expressions"]
SLOTS: tuple[Slot, ...] = ("portrait", "front", "side", "back", "expressions")
SlotStatus = Literal["present", "candidate", "missing"]
_VIEW_SLOTS: tuple[Slot, ...] = ("front", "side", "back")


@dataclass(frozen=True, slots=True)
class FillLine:
    """One job of the plan."""

    wave: int
    slots: tuple[Slot, ...]
    params: dict[str, Any] = field(hash=False)

    @property
    def output_count(self) -> int:
        """Images the job is priced for (one per view; one otherwise)."""
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
    return {
        "portrait": _status(portraits),
        "front": _status([e for e in entries if e.entry_type == AssetEntryType.CHARACTER_SHEET]),
        "side": _status(
            [e for e in entries if e.entry_type == AssetEntryType.VIEW and e.view == "side"]
        ),
        "back": _status(
            [e for e in entries if e.entry_type == AssetEntryType.VIEW and e.view == "back"]
        ),
        "expressions": _status(
            [e for e in entries if e.entry_type == AssetEntryType.EXPRESSION_SHEET]
        ),
    }


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
    views = [slot for slot in _VIEW_SLOTS if slot in wanted]
    if views:
        wave += 1
        lines.append(
            FillLine(
                wave=wave,
                slots=tuple(views),
                params={
                    **base,
                    "prompt": _prompt(character, look, with_outfit=True),
                    "target_variant_id": look.id,
                    "character_views": [CharacterViewAngle(v).value for v in views],
                },
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
