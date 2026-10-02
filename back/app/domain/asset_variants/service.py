"""Looks / variants and their entries, shared by characters and scenes.

The tables (`SkillAssetVariant`, `SkillAssetEntry`) are the only source of
truth. Two read shapes come out of them:

- the structured one (variants → entries) for the P1 API and the resolver;
- `project(skill)`: the flat, P0-shaped `reference_assets` list
  (`{asset_id, view, label, created_at}`) every existing reader expects —
  `CharacterView`/`SceneView`, the admin views, iOS. `sync_mirror` writes that
  same projection back into `params_json[...]["reference_assets"]` after each
  change, so code that still reads the raw JSON (canvas thumbnails, the
  front's `firstSkillReferenceAssetId`, the skill detail `params`) stays right
  until it moves over, and the P1 migration's downgrade loses nothing.

Every mutation goes through the relationships (`skill.asset_variants`,
`variant.entries`) so the in-memory collections stay consistent within a
request, and ends with `sync_mirror`.

Candidates (P2-1): a generated image filed into a *slot* that already holds
an approved image — a look's front sheet, one side/back view, one set of
expressions, the card's identity portrait, a variant's master plate — is
kept as a `candidate` beside it instead of replacing it (`file_generated`).
`approve_entry` swaps the two. Every read meant for someone other than the
owner's own editor (the flat projection, the mirror, defaults, thumbnails,
an unlocked card's detail) sees approved entries only, and the entry caps
count approved entries only — candidates are kept until the owner deletes
them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.models import Asset, CreationSkill, SkillAssetEntry, SkillAssetVariant
from app.models.enums import (
    CHARACTER_ENTRY_TYPES,
    SCENE_ENTRY_TYPES,
    AssetEntryStatus,
    AssetEntryType,
    AssetVariantKind,
    CreationSkillCategory,
    MediaType,
)

DEFAULT_LOOK_NAME = "默认造型"
DEFAULT_SCENE_VARIANT_NAME = "主场景"
# Character looks only. Scene cards are uncapped (P2-5, decided 2026-10-02):
# a lighting × weather × state × period matrix runs past any fixed number;
# a scene variant still holds at most `MAX_ENTRIES_PER_VARIANT` approved.
MAX_VARIANTS_PER_SKILL = 12
MAX_ENTRIES_PER_VARIANT = 24
MAX_ENTRIES_PER_SKILL = 120
MAX_VARIANT_NAME_LEN = 40

_MIRROR_KEY = {
    CreationSkillCategory.CHARACTER.value: "character",
    CreationSkillCategory.SCENE_ASSET.value: "scene",
}


def is_character(skill: CreationSkill) -> bool:
    return skill.category == CreationSkillCategory.CHARACTER


def _kind(skill: CreationSkill) -> str:
    return (AssetVariantKind.LOOK if is_character(skill) else AssetVariantKind.SCENE_VARIANT).value


def _default_name(skill: CreationSkill) -> str:
    return DEFAULT_LOOK_NAME if is_character(skill) else DEFAULT_SCENE_VARIANT_NAME


# ---- reads ------------------------------------------------------------------


def variants(skill: CreationSkill) -> list[SkillAssetVariant]:
    """Default first, then `sort_order` (the relationship's own ordering)."""
    return list(skill.asset_variants)


def find_default(skill: CreationSkill) -> SkillAssetVariant | None:
    return next((variant for variant in skill.asset_variants if variant.is_default), None)


def find_variant(skill: CreationSkill, variant_id: str) -> SkillAssetVariant | None:
    return next((v for v in skill.asset_variants if v.id == variant_id), None)


def find_by_name(skill: CreationSkill, name: str) -> SkillAssetVariant | None:
    clean = name.strip()
    return next((v for v in skill.asset_variants if v.name == clean), None)


def entries(skill: CreationSkill) -> list[SkillAssetEntry]:
    """Every entry: the anchor first, then variant order, then entry order."""
    ordered = [entry for variant in skill.asset_variants for entry in variant.entries]
    anchor = [entry for entry in ordered if entry.is_anchor]
    return anchor + [entry for entry in ordered if not entry.is_anchor]


def is_approved(entry: SkillAssetEntry) -> bool:
    return entry.status == AssetEntryStatus.APPROVED


def approved_entries(skill: CreationSkill) -> list[SkillAssetEntry]:
    """`entries`, without candidates — what anyone but the owner's own
    editor gets to see or use."""
    return [entry for entry in entries(skill) if is_approved(entry)]


def anchor(skill: CreationSkill) -> SkillAssetEntry | None:
    return next((entry for entry in entries(skill) if entry.is_anchor), None)


def identity_portrait(skill: CreationSkill) -> SkillAssetEntry | None:
    """The card's approved identity portrait (定妆照): the anchor when it is
    one, else the first approved portrait."""
    portraits = [
        entry
        for entry in approved_entries(skill)
        if entry.entry_type == AssetEntryType.IDENTITY_PORTRAIT
    ]
    return portraits[0] if portraits else None


def asset_ids(skill: CreationSkill) -> list[str]:
    return list(dict.fromkeys(entry.asset_id for entry in approved_entries(skill)))


def _projected_view(skill: CreationSkill, entry: SkillAssetEntry) -> str:
    if is_character(skill):
        if entry.entry_type == AssetEntryType.CHARACTER_SHEET:
            return "front"
        if entry.entry_type == AssetEntryType.VIEW and entry.view:
            return entry.view
        return "general"
    if entry.entry_type == AssetEntryType.MASTER:
        return "establishing"
    return entry.view or "general"


def project(skill: CreationSkill) -> list[dict[str, Any]]:
    """The P0 `reference_assets` shape, plus `variant_id`/`entry_type`/
    `is_anchor`. A non-default look's entries carry the look's name as their
    `label` — P0's meaning of a label (the outfit/variant it belongs to).
    Approved entries only: every reader of this shape treats it as the card's
    settled set of references."""
    projected: list[dict[str, Any]] = []
    for entry in approved_entries(skill):
        variant = entry.variant
        label = entry.label if variant.is_default else variant.name
        projected.append(
            {
                "asset_id": entry.asset_id,
                "view": _projected_view(skill, entry),
                "label": label,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "variant_id": variant.id,
                "entry_type": entry.entry_type,
                "is_anchor": entry.is_anchor,
            }
        )
    return projected


def moderation_texts(skill: CreationSkill) -> list[str]:
    """Look/variant names, descriptions and entry labels — text a publish
    must moderate now that it no longer sits inside `params_json`."""
    texts: list[str] = []
    for variant in skill.asset_variants:
        texts.extend(t for t in (variant.name, variant.description) if t)
        texts.extend(entry.label for entry in variant.entries if entry.label)
    return texts


# ---- writes -----------------------------------------------------------------


def sync_mirror(session: Session, skill: CreationSkill) -> None:
    """Writes `project(skill)` (P0 keys only) into the JSON mirror. A new
    dict is assigned so the JSONB column is marked dirty (DM invariant 11)."""
    key = _MIRROR_KEY.get(skill.category)
    if key is None:
        return
    current = dict(skill.params_json or {})
    nested = dict(current.get(key) or {}) if isinstance(current.get(key), dict) else {}
    nested["reference_assets"] = [
        {k: item[k] for k in ("asset_id", "view", "label", "created_at")} for item in project(skill)
    ]
    skill.params_json = {**current, key: nested}
    # Flushed so a later `expire`/refresh in the same request can't drop it.
    session.flush()


def ensure_default(session: Session, skill: CreationSkill) -> SkillAssetVariant:
    existing = find_default(skill)
    if existing is not None:
        return existing
    variant = SkillAssetVariant(
        skill_id=skill.id,
        kind=_kind(skill),
        name=_default_name(skill),
        is_default=True,
        sort_order=0,
    )
    skill.asset_variants.append(variant)
    session.flush()
    return variant


def _check_variant_name(skill: CreationSkill, name: str, *, exclude_id: str | None = None) -> str:
    clean = name.strip()[:MAX_VARIANT_NAME_LEN]
    if not clean:
        raise ValidationFailed("名称不能为空。", fields={"name": "不能为空"})
    clash = find_by_name(skill, clean)
    if clash is not None and clash.id != exclude_id:
        raise ValidationFailed("已有同名的造型/变体。", fields={"name": "名称已存在"})
    return clean


def create_variant(
    session: Session,
    skill: CreationSkill,
    *,
    name: str,
    description: str | None = None,
    presets: dict[str, Any] | None = None,
) -> SkillAssetVariant:
    ensure_default(session, skill)
    if is_character(skill) and len(skill.asset_variants) >= MAX_VARIANTS_PER_SKILL:
        raise ValidationFailed(
            f"每个{'角色' if is_character(skill) else '场景'}最多 {MAX_VARIANTS_PER_SKILL} 个"
            f"{'造型' if is_character(skill) else '变体'}。",
            fields={"name": "数量已达上限"},
        )
    variant = SkillAssetVariant(
        skill_id=skill.id,
        kind=_kind(skill),
        name=_check_variant_name(skill, name),
        description=(description or "").strip() or None,
        presets_json=dict(presets or {}),
        is_default=False,
        sort_order=max((v.sort_order for v in skill.asset_variants), default=0) + 1,
    )
    skill.asset_variants.append(variant)
    session.flush()
    sync_mirror(session, skill)
    return variant


def find_or_create_variant(
    session: Session,
    skill: CreationSkill,
    *,
    name: str | None = None,
    presets: dict[str, Any] | None = None,
) -> SkillAssetVariant:
    """Write-back's lookup: by `presets` (exact match) when given, else by
    name; `None`/blank for both means the default."""
    if presets:
        match = next((v for v in skill.asset_variants if v.presets_json == presets), None)
        if match is not None:
            return match
    clean = (name or "").strip()[:MAX_VARIANT_NAME_LEN]
    if not clean and not presets:
        return ensure_default(session, skill)
    if clean:
        existing = find_by_name(skill, clean)
        if existing is not None:
            return existing
    return create_variant(session, skill, name=clean or "变体", presets=presets)


def update_variant(
    session: Session,
    skill: CreationSkill,
    variant: SkillAssetVariant,
    *,
    name: str | None = None,
    description: str | None = None,
    presets: dict[str, Any] | None = None,
    sort_order: int | None = None,
    make_default: bool = False,
) -> SkillAssetVariant:
    if name is not None:
        variant.name = _check_variant_name(skill, name, exclude_id=variant.id)
    if description is not None:
        variant.description = description.strip() or None
    if presets is not None:
        variant.presets_json = dict(presets)
    if sort_order is not None:
        variant.sort_order = sort_order
    if make_default and not variant.is_default:
        current = find_default(skill)
        if current is not None:
            current.is_default = False
            # The partial unique index allows one default at a time.
            session.flush()
        variant.is_default = True
    session.flush()
    sync_mirror(session, skill)
    return variant


def delete_variant(session: Session, skill: CreationSkill, variant: SkillAssetVariant) -> None:
    if variant.is_default:
        raise ValidationFailed(
            "默认造型/变体不能删除，请先把另一个设为默认。", fields={"variant_id": "默认项不可删除"}
        )
    skill.asset_variants.remove(variant)
    session.flush()
    sync_mirror(session, skill)


def _check_entry_type(skill: CreationSkill, entry_type: str) -> None:
    allowed = CHARACTER_ENTRY_TYPES if is_character(skill) else SCENE_ENTRY_TYPES
    if entry_type not in allowed:
        raise ValidationFailed("参考图类型与卡片类别不匹配。", fields={"entry_type": "类型无效"})


# Entry types that fill one slot — a newer generated image of the same slot
# becomes a candidate instead of replacing the approved one.
_SLOT_TYPES = frozenset(
    {
        AssetEntryType.IDENTITY_PORTRAIT.value,
        AssetEntryType.CHARACTER_SHEET.value,
        AssetEntryType.VIEW.value,
        AssetEntryType.EXPRESSION_SHEET.value,
        AssetEntryType.MASTER.value,
    }
)


def _expression_set(expressions: list[Any] | None) -> tuple[str, ...]:
    return tuple(sorted(str(item) for item in expressions or []))


def slot_mates(
    skill: CreationSkill,
    variant: SkillAssetVariant,
    *,
    entry_type: str,
    view: str | None,
    expressions: list[Any] | None,
    exclude: SkillAssetEntry | None = None,
) -> list[SkillAssetEntry]:
    """Every entry (any status) competing for the same slot, or `[]` for a
    type that has none (poses, details, props, shots, other accumulate).

    The identity portrait is card-wide (one face for every look); the other
    slots are per look / variant: the front sheet, each single view, each
    distinct set of expressions, the master plate.
    """
    if entry_type not in _SLOT_TYPES:
        return []
    if entry_type == AssetEntryType.IDENTITY_PORTRAIT:
        pool = entries(skill)
    else:
        pool = list(variant.entries)
    wanted = _expression_set(expressions)
    mates: list[SkillAssetEntry] = []
    for entry in pool:
        if entry is exclude or entry.entry_type != entry_type:
            continue
        if entry_type == AssetEntryType.VIEW and entry.view != view:
            continue
        if (
            entry_type == AssetEntryType.EXPRESSION_SHEET
            and _expression_set(entry.expressions_json) != wanted
        ):
            continue
        mates.append(entry)
    return mates


def _approved_counts(skill: CreationSkill, variant: SkillAssetVariant) -> tuple[int, int]:
    in_variant = sum(1 for e in variant.entries if is_approved(e))
    return in_variant, len(approved_entries(skill))


def _check_approved_room(skill: CreationSkill, variant: SkillAssetVariant, field: str) -> None:
    """The caps limit approved entries only; candidates never block a write."""
    in_variant, in_skill = _approved_counts(skill, variant)
    if in_variant >= MAX_ENTRIES_PER_VARIANT:
        raise ValidationFailed(
            f"每个造型/变体最多 {MAX_ENTRIES_PER_VARIANT} 张定稿参考图。",
            fields={field: "数量已达上限"},
        )
    if is_character(skill) and in_skill >= MAX_ENTRIES_PER_SKILL:
        raise ValidationFailed(
            f"每张卡片最多 {MAX_ENTRIES_PER_SKILL} 张定稿参考图。",
            fields={field: "数量已达上限"},
        )


def file_generated(
    session: Session,
    skill: CreationSkill,
    variant: SkillAssetVariant,
    *,
    asset_id: str,
    entry_type: str,
    view: str | None = None,
    label: str | None = None,
    expressions: list[str] | None = None,
    source_job_id: str | None = None,
) -> SkillAssetEntry:
    """Files a generated image: approved when its slot holds no approved
    image yet (and the caps leave room), otherwise a candidate beside it.
    Never replaces or evicts anything."""
    mates = slot_mates(skill, variant, entry_type=entry_type, view=view, expressions=expressions)
    in_variant, in_skill = _approved_counts(skill, variant)
    room = in_variant < MAX_ENTRIES_PER_VARIANT and (
        not is_character(skill) or in_skill < MAX_ENTRIES_PER_SKILL
    )
    taken = any(is_approved(m) and m.asset_id != asset_id for m in mates)
    status = AssetEntryStatus.APPROVED if room and not taken else AssetEntryStatus.CANDIDATE
    return add_entry(
        session,
        skill,
        variant,
        asset_id=asset_id,
        entry_type=entry_type,
        view=view,
        label=label,
        expressions=expressions,
        source_job_id=source_job_id,
        status=status.value,
    )


def approve_entry(
    session: Session, skill: CreationSkill, entry: SkillAssetEntry
) -> SkillAssetEntry:
    """Makes `entry` the slot's approved image. The one it displaces goes
    back to candidate (kept, never deleted) and hands over the anchor if it
    held it. Over the approved caps is a 422."""
    if is_approved(entry):
        return entry
    displaced = [
        mate
        for mate in slot_mates(
            skill,
            entry.variant,
            entry_type=entry.entry_type,
            view=entry.view,
            expressions=entry.expressions_json,
            exclude=entry,
        )
        if is_approved(mate)
    ]
    if not displaced:
        _check_approved_room(skill, entry.variant, "status")
    moves_anchor = any(mate.is_anchor for mate in displaced)
    for mate in displaced:
        mate.status = AssetEntryStatus.CANDIDATE.value
    entry.status = AssetEntryStatus.APPROVED.value
    session.flush()
    if moves_anchor:
        set_anchor(session, skill, entry, sync=False)
    prefer_portrait_anchor(session, skill, entry, sync=False)
    sync_mirror(session, skill)
    return entry


def prefer_portrait_anchor(
    session: Session, skill: CreationSkill, entry: SkillAssetEntry, *, sync: bool = True
) -> None:
    """An approved identity portrait (定妆照) is the anchor of choice: it
    takes over from no anchor or from a sheet (the P1 automatic anchor), but
    never from another portrait — the owner can still re-anchor by hand."""
    if entry.entry_type != AssetEntryType.IDENTITY_PORTRAIT or not is_approved(entry):
        return
    current = anchor(skill)
    if current is None or current.entry_type == AssetEntryType.CHARACTER_SHEET:
        set_anchor(session, skill, entry, sync=sync)


def add_entry(
    session: Session,
    skill: CreationSkill,
    variant: SkillAssetVariant,
    *,
    asset_id: str,
    entry_type: str,
    view: str | None = None,
    label: str | None = None,
    expressions: list[str] | None = None,
    source_job_id: str | None = None,
    sync: bool = True,
    status: str = AssetEntryStatus.APPROVED.value,
) -> SkillAssetEntry:
    """Files `asset_id` under `variant`. Re-adding an asset already in that
    variant updates the existing entry instead of duplicating it (keeping
    its status). Over an approved-entry limit is a 422 — never a silent
    eviction; a candidate never counts against it."""
    _check_entry_type(skill, entry_type)
    existing = next((e for e in variant.entries if e.asset_id == asset_id), None)
    if existing is None:
        if status == AssetEntryStatus.APPROVED:
            _check_approved_room(skill, variant, "reference_asset_ids")
        existing = SkillAssetEntry(
            skill_id=skill.id,
            asset_id=asset_id,
            entry_type=entry_type,
            status=status,
            sort_order=max((e.sort_order for e in variant.entries), default=-1) + 1,
        )
        variant.entries.append(existing)
    existing.entry_type = entry_type
    if entry_type == AssetEntryType.MASTER and is_approved(existing):
        _demote_other_masters(variant, existing)
    existing.view = view
    existing.label = (label or "").strip()[:60] or None
    existing.expressions_json = list(expressions) if expressions else None
    if source_job_id:
        existing.source_job_id = source_job_id
    session.flush()
    if sync:
        sync_mirror(session, skill)
    return existing


def remove_entry(session: Session, skill: CreationSkill, entry: SkillAssetEntry) -> None:
    entry.variant.entries.remove(entry)
    session.flush()
    sync_mirror(session, skill)


def remove_asset(session: Session, skill: CreationSkill, asset_id: str) -> int:
    """Removes `asset_id` from every look/variant of the card."""
    removed = 0
    for variant in skill.asset_variants:
        for entry in [e for e in variant.entries if e.asset_id == asset_id]:
            variant.entries.remove(entry)
            removed += 1
    session.flush()
    sync_mirror(session, skill)
    return removed


def set_anchor(
    session: Session, skill: CreationSkill, entry: SkillAssetEntry | None, *, sync: bool = True
) -> None:
    """Moves the card's single anchor to `entry` (or clears it). Only an
    approved image can be the identity every job leads with (422)."""
    if entry is not None and not is_approved(entry):
        raise ValidationFailed("候选图需要先定稿，才能设为锚点。", fields={"entry_id": "未定稿"})
    for other in entries(skill):
        if other.is_anchor and other is not entry:
            other.is_anchor = False
    # The partial unique index allows one anchor at a time.
    session.flush()
    if entry is not None:
        entry.is_anchor = True
        session.flush()
    if sync:
        sync_mirror(session, skill)


def set_members(session: Session, skill: CreationSkill, asset_ids_in_order: list[str]) -> None:
    """The legacy flat-list edit (`reference_asset_ids` on create/PATCH):
    drops entries whose asset is no longer listed, files new ones under the
    default as `other`, and keeps every surviving entry's type, view and
    look — an id-only edit form must not erase which image is the 婚礼 sheet.
    Candidates are left alone: the flat list is built from the approved
    projection, so a candidate's absence from it means nothing."""
    wanted = list(dict.fromkeys(asset_ids_in_order))
    default = ensure_default(session, skill)
    for variant in skill.asset_variants:
        stale = [e for e in variant.entries if e.asset_id not in wanted and is_approved(e)]
        for entry in stale:
            variant.entries.remove(entry)
    session.flush()
    known = {entry.asset_id for entry in entries(skill)}
    for entry in entries(skill):
        if entry.asset_id in wanted and not is_approved(entry):
            # Listing a candidate in the flat edit approves it.
            entry.status = AssetEntryStatus.APPROVED.value
    for asset_id in wanted:
        if asset_id not in known:
            add_entry(
                session,
                skill,
                default,
                asset_id=asset_id,
                entry_type=AssetEntryType.OTHER.value,
                sync=False,
            )
    for order, asset_id in enumerate(wanted):
        for entry in default.entries:
            if entry.asset_id == asset_id:
                entry.sort_order = order
    session.flush()
    sync_mirror(session, skill)


def is_identity_portrait(session: Session, asset_id: str) -> bool:
    """`asset_id` is an approved identity portrait (定妆照) on some card."""
    found = session.scalar(
        select(SkillAssetEntry.id)
        .where(
            SkillAssetEntry.asset_id == asset_id,
            SkillAssetEntry.entry_type == AssetEntryType.IDENTITY_PORTRAIT.value,
            SkillAssetEntry.status == AssetEntryStatus.APPROVED.value,
        )
        .limit(1)
    )
    return found is not None


def skills_referencing_asset(session: Session, asset_id: str) -> list[str]:
    return list(
        session.scalars(
            select(SkillAssetEntry.skill_id).where(SkillAssetEntry.asset_id == asset_id).distinct()
        )
    )


# ---- job references ----------------------------------------------------------

MAX_DEFAULT_CHARACTER_REFERENCES = 3
MAX_DEFAULT_SCENE_REFERENCES = 2
_SHEET_ORDER = {"front": 0, "side": 1, "back": 2}


def _approved(items: list[SkillAssetEntry]) -> list[SkillAssetEntry]:
    return [e for e in items if e.status == AssetEntryStatus.APPROVED]


def default_subset(skill: CreationSkill, variant: SkillAssetVariant | None = None) -> list[str]:
    """What a job gets from this card when the caller named at most a look.

    Character: the anchor (only when it is the default look's — or, for
    another look, only a face-only `identity_portrait`), then the look's
    sheet and single views front → side → back, else its other non-
    expression images; at most 3. Scene: the variant's master then its
    shots, else the card's anchor (the structure every variant shares); at
    most 2. With no look named and nothing in the default, anything.
    """
    target = variant or find_default(skill)
    target_entries = _approved(list(target.entries)) if target else []
    picked: list[str] = []
    card_anchor = anchor(skill)

    if is_character(skill):
        if card_anchor is not None and card_anchor.status == AssetEntryStatus.APPROVED:
            same_look = target is not None and card_anchor.variant_id == target.id
            face_only = card_anchor.entry_type == AssetEntryType.IDENTITY_PORTRAIT
            if same_look or face_only:
                picked.append(card_anchor.asset_id)
        sheets = sorted(
            (
                e
                for e in target_entries
                if e.entry_type in (AssetEntryType.CHARACTER_SHEET, AssetEntryType.VIEW)
            ),
            key=lambda e: _SHEET_ORDER.get(
                "front" if e.entry_type == AssetEntryType.CHARACTER_SHEET else (e.view or ""), 3
            ),
        )
        pool = sheets or [
            e for e in target_entries if e.entry_type != AssetEntryType.EXPRESSION_SHEET
        ]
        limit = MAX_DEFAULT_CHARACTER_REFERENCES
    else:
        masters = [e for e in target_entries if e.entry_type == AssetEntryType.MASTER]
        pool = masters + [e for e in target_entries if e.entry_type != AssetEntryType.MASTER]
        if not pool and card_anchor is not None:
            pool = [card_anchor]
        limit = MAX_DEFAULT_SCENE_REFERENCES

    if not pool and not picked and variant is None:
        pool = entries(skill)
    for entry in pool:
        if entry.asset_id not in picked:
            picked.append(entry.asset_id)
    return picked[:limit]


def select_assets(
    skill: CreationSkill,
    *,
    variant_id: str | None,
    asset_ids: list[str] | None,
    owner: str,
    field: str,
) -> list[str]:
    """A caller's `*_ref_selection` item for this card: a look (its default
    subset), exact images (each one of the card's own), or both (the images
    must be in that look). Anything else is a 422 — a selection can narrow
    what a card contributes, never smuggle in another asset."""
    variant = None
    if variant_id:
        variant = find_variant(skill, variant_id)
        if variant is None:
            raise ValidationFailed(
                f"{owner}的造型/变体不存在。", fields={field: "variant_id 不属于该卡片"}
            )
    if not asset_ids:
        return default_subset(skill, variant)
    pool = variant.entries if variant is not None else entries(skill)
    owned = {e.asset_id for e in pool}
    if any(asset_id not in owned for asset_id in asset_ids):
        raise ValidationFailed(
            f"{owner}的参考图选择无效。", fields={field: "只能选择该卡片（造型）自己的参考图"}
        )
    return list(dict.fromkeys(asset_ids))


_ENTRY_TYPE_NAMES = {
    AssetEntryType.IDENTITY_PORTRAIT: "定妆照",
    AssetEntryType.CHARACTER_SHEET: "设定图",
    AssetEntryType.EXPRESSION_SHEET: "表情合集",
    AssetEntryType.POSE: "姿态",
    AssetEntryType.OUTFIT_DETAIL: "服装细节",
    AssetEntryType.PROP: "道具",
    AssetEntryType.MASTER: "主图",
    AssetEntryType.SHOT: "机位",
}
_VIEW_NAMES = {"side": "侧面", "back": "背面", "detail": "细节", "reverse": "反打"}


def entry_label(skill: CreationSkill, entry: SkillAssetEntry) -> str:
    """`角色「林夏」·婚礼·设定图` / `场景「客厅」·黄昏·主图` — what the
    prompt's reference legend calls this image."""
    noun = "角色" if is_character(skill) else "场景"
    parts = [f"{noun}「{skill.title}」"]
    if not entry.variant.is_default:
        parts.append(entry.variant.name)
    positional = entry.entry_type in (AssetEntryType.VIEW, AssetEntryType.SHOT)
    if positional and entry.view in _VIEW_NAMES:
        parts.append(_VIEW_NAMES[entry.view])
    else:
        parts.append(_ENTRY_TYPE_NAMES.get(AssetEntryType(entry.entry_type), "参考图"))
    return "·".join(parts)[:60]


# ---- direct edits (P1 API) ------------------------------------------------------

CHARACTER_VIEWS = frozenset({"front", "side", "back", "three_quarter"})
SCENE_VIEWS = frozenset({"detail", "reverse"})


def find_entry(skill: CreationSkill, entry_id: str) -> SkillAssetEntry | None:
    return next((entry for entry in entries(skill) if entry.id == entry_id), None)


def check_view(skill: CreationSkill, view: str | None) -> str | None:
    clean = (view or "").strip() or None
    allowed = CHARACTER_VIEWS if is_character(skill) else SCENE_VIEWS
    if clean is not None and clean not in allowed:
        raise ValidationFailed("视角无效。", fields={"view": f"可选：{'/'.join(sorted(allowed))}"})
    return clean


def update_entry(
    session: Session,
    skill: CreationSkill,
    entry: SkillAssetEntry,
    *,
    variant: SkillAssetVariant | None = None,
    entry_type: str | None = None,
    view: str | None = None,
    clear_view: bool = False,
    label: str | None = None,
    expressions: list[str] | None = None,
    status: str | None = None,
) -> SkillAssetEntry:
    """Edits one entry; `variant` moves it to another look of the same card
    (an asset already in the target look is a 422 — the pair is unique)."""
    if entry_type is not None:
        _check_entry_type(skill, entry_type)
        entry.entry_type = entry_type
        if entry_type == AssetEntryType.MASTER and is_approved(entry):
            _demote_other_masters(variant or entry.variant, entry)
    if view is not None or clear_view:
        entry.view = None if clear_view else check_view(skill, view)
    if label is not None:
        entry.label = label.strip()[:60] or None
    if expressions is not None:
        entry.expressions_json = list(expressions) or None
    if status == AssetEntryStatus.CANDIDATE and is_approved(entry):
        if entry.is_anchor:
            raise ValidationFailed(
                "锚点不能改为候选，请先把锚点设到另一张图。", fields={"status": "锚点"}
            )
        entry.status = AssetEntryStatus.CANDIDATE.value
    if variant is not None and variant is not entry.variant:
        if any(e.asset_id == entry.asset_id for e in variant.entries):
            raise ValidationFailed("目标造型/变体里已有这张图。", fields={"variant_id": "重复"})
        if is_approved(entry):
            _check_approved_room(skill, variant, "variant_id")
        entry.variant.entries.remove(entry)
        session.flush()
        moved = SkillAssetEntry(
            skill_id=skill.id,
            asset_id=entry.asset_id,
            entry_type=entry.entry_type,
            view=entry.view,
            label=entry.label,
            expressions_json=entry.expressions_json,
            status=entry.status,
            is_anchor=entry.is_anchor,
            source_job_id=entry.source_job_id,
            created_at=entry.created_at,
            sort_order=max((e.sort_order for e in variant.entries), default=-1) + 1,
        )
        variant.entries.append(moved)
        entry = moved
    session.flush()
    if status == AssetEntryStatus.APPROVED and not is_approved(entry):
        return approve_entry(session, skill, entry)
    sync_mirror(session, skill)
    return entry


def _demote_other_masters(variant: SkillAssetVariant, keep: SkillAssetEntry) -> None:
    """One approved master plate per scene variant: any other approved one
    becomes a shot (candidate masters keep competing for the slot)."""
    for other in variant.entries:
        if other is not keep and other.entry_type == AssetEntryType.MASTER and is_approved(other):
            other.entry_type = AssetEntryType.SHOT.value


def require_owned_media(session: Session, *, user_id: str, asset_id: str) -> Asset:
    """An image/video the caller owns — what a card may file. Missing and
    someone else's both 404 (existence is not confirmed)."""
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != user_id:
        raise NotFound("参考素材不存在。")
    if asset.media_type not in (MediaType.IMAGE, MediaType.VIDEO):
        raise ValidationFailed(
            "参考素材必须是图片或视频。", fields={"asset_id": "必须是图片或视频"}
        )
    return asset
