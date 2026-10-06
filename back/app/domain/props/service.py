"""Prop library (道具, AC-4) — reusable objects a shot can hold or show.

A prop is a `CreationSkill` with `category=PROP_ASSET`, its text under
`params_json["prop"]` — the same adapter shape as `scenes.service` (see
`PropView`). Its images live in the variants tables: one variant per
condition (全新 / 旧化 / 破损…, `presets_json.prop_state`), each with a hero
plate (`master`), turntable views (`view`, one slot per camera pose) and
detail / in-use shots (`shot`). A job pulls props in via
`GenerationParams.prop_ids` (`apply_prop_refs`), sharing the 9-slot
reference budget after characters and scenes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as asset_variants_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.image_assets import camera as camera_vocab
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill
from app.models.enums import AssetEntryType, CreationSkillCategory, MediaType

MAX_REFERENCE_ASSETS = asset_variants_service.MAX_ENTRIES_PER_VARIANT
MAX_JOB_REFERENCE_ASSETS = 9
MAX_SELECTED_PROPS = 4
HERO_VIEW = "hero"
DEFAULT_VIEW = "general"
PROP_PARAMS_KEY = "prop"

_REFERENCE_MEDIA_TYPES = (MediaType.IMAGE, MediaType.VIDEO)


@dataclass(slots=True)
class PropView:
    """A prop-shaped projection of the underlying `CreationSkill` row."""

    skill: CreationSkill

    @property
    def id(self) -> str:
        return self.skill.id

    @property
    def name(self) -> str:
        return self.skill.title

    @property
    def description(self) -> str | None:
        return _payload(self.skill).get("description") or None

    @property
    def reference_assets(self) -> list[dict[str, Any]]:
        """The flat projection (`asset_variants.service.project`): the hero
        plate first, tagged `hero`."""
        return asset_variants_service.project(self.skill)

    @property
    def reference_asset_ids(self) -> list[str]:
        return [str(entry["asset_id"]) for entry in self.reference_assets if entry.get("asset_id")]

    @property
    def status(self) -> str:
        return self.skill.status

    @property
    def visibility(self) -> str:
        return self.skill.visibility

    @property
    def access_credits(self) -> int:
        return self.skill.access_credits

    @property
    def created_at(self) -> dt.datetime:
        return self.skill.created_at

    @property
    def updated_at(self) -> dt.datetime:
        return self.skill.updated_at


def _payload(skill: CreationSkill) -> dict[str, Any]:
    """A shallow copy — never the live dict (CL invariant 10)."""
    raw = skill.params_json.get(PROP_PARAMS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _set_payload(skill: CreationSkill, payload: dict[str, Any]) -> None:
    skill.params_json = {**skill.params_json, PROP_PARAMS_KEY: payload}


def _short_description(description: str | None) -> str:
    return (description or "").strip()[:300]


def owned_prop_skill(session: Session, *, user_id: str, prop_id: str) -> CreationSkill:
    skill = session.get(CreationSkill, prop_id)
    # Missing, someone else's and a non-prop skill all 404 alike.
    if (
        skill is None
        or skill.owner_user_id != user_id
        or skill.category != CreationSkillCategory.PROP_ASSET
    ):
        raise NotFound("道具不存在。")
    return skill


def _validate_reference_assets(
    session: Session, *, user_id: str, asset_ids: list[str]
) -> list[str]:
    deduped = list(dict.fromkeys(asset_ids))
    if len(deduped) > MAX_REFERENCE_ASSETS:
        raise ValidationFailed(
            f"参考素材最多 {MAX_REFERENCE_ASSETS} 个。",
            fields={"reference_asset_ids": f"不能超过 {MAX_REFERENCE_ASSETS} 个"},
        )
    for asset_id in deduped:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_user_id != user_id:
            raise NotFound("参考素材不存在。")
        if asset.media_type not in _REFERENCE_MEDIA_TYPES:
            raise ValidationFailed(
                "道具参考素材必须是图片或视频。", fields={"reference_asset_ids": "必须是图片或视频"}
            )
    return deduped


def _promote_master(session: Session, skill: CreationSkill) -> None:
    """With no anchor yet, the default variant's first approved image becomes
    its hero plate (`master`) and the card's anchor — as for a scene."""
    if asset_variants_service.anchor(skill) is not None:
        return
    default = asset_variants_service.find_default(skill)
    approved = (
        [e for e in default.entries if asset_variants_service.is_approved(e)] if default else []
    )
    first = approved[0] if approved else None
    if first is None:
        return
    first.entry_type = AssetEntryType.MASTER.value
    first.view = None
    first.camera_json = None
    asset_variants_service.set_anchor(session, skill, first)


def create_prop(
    session: Session,
    *,
    user_id: str,
    name: str,
    description: str | None,
    reference_asset_ids: list[str],
) -> PropView:
    refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
    clean_description = (description or "").strip() or None
    skill = skill_library_service.create(
        session,
        owner_user_id=user_id,
        title=name.strip(),
        description=_short_description(clean_description),
        category=CreationSkillCategory.PROP_ASSET,
        params_json={PROP_PARAMS_KEY: {"description": clean_description}},
        cover_asset_id=None,
    )
    asset_variants_service.ensure_default(session, skill)
    asset_variants_service.set_members(session, skill, refs)
    _promote_master(session, skill)
    return PropView(skill)


def list_props(session: Session, *, user_id: str) -> list[PropView]:
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == user_id,
            CreationSkill.category == CreationSkillCategory.PROP_ASSET,
        )
        .order_by(CreationSkill.created_at.desc())
    )
    return [PropView(skill) for skill in session.scalars(stmt)]


def get_prop(session: Session, *, user_id: str, prop_id: str) -> PropView:
    return PropView(owned_prop_skill(session, user_id=user_id, prop_id=prop_id))


def update_prop(
    session: Session,
    *,
    user_id: str,
    prop_id: str,
    name: str | None = None,
    description: str | None = None,
    reference_asset_ids: list[str] | None = None,
) -> PropView:
    skill = owned_prop_skill(session, user_id=user_id, prop_id=prop_id)
    payload = _payload(skill)
    if name is not None:
        skill.title = name.strip()
    if description is not None:
        clean = description.strip() or None
        payload["description"] = clean
        skill.description = _short_description(clean)
    _set_payload(skill, payload)
    if reference_asset_ids is not None:
        refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
        asset_variants_service.set_members(session, skill, refs)
        _promote_master(session, skill)
    skill_library_service.withdraw_after_edit(session, skill)
    session.flush()
    return PropView(skill)


def delete_prop(session: Session, *, user_id: str, prop_id: str) -> None:
    skill = owned_prop_skill(session, user_id=user_id, prop_id=prop_id)
    skill_library_service.delete(session, skill=skill, actor_user_id=user_id)


def append_reference_asset(
    session: Session,
    *,
    user_id: str,
    prop_id: str,
    asset_id: str,
    view: str = DEFAULT_VIEW,
    label: str | None = None,
    presets: dict[str, Any] | None = None,
    source_job_id: str | None = None,
    variant_id: str | None = None,
    generated: bool = False,
    entry_type: str | None = None,
    copy_from_entry_id: str | None = None,
    camera: dict[str, Any] | None = None,
) -> PropView:
    """Files one image under a variant, like `scenes.append_reference_asset`:
    `variant_id` wins, else `presets` / `label` pick (or create) it. The
    variant's first image becomes its hero plate (`master`); a posed image
    (`camera`, AC-2) is a turntable `view` with one slot per pose; anything
    else is a `shot`. `generated` never displaces an approved image (it
    becomes a candidate); `copy_from_entry_id` / `entry_type` are the P6
    write-back overrides."""
    skill = owned_prop_skill(session, user_id=user_id, prop_id=prop_id)
    _validate_reference_assets(session, user_id=user_id, asset_ids=[asset_id])
    clean_label = (label or "").strip() or None
    variant = (
        asset_variants_service.find_variant(skill, variant_id) if variant_id else None
    ) or asset_variants_service.find_or_create_variant(
        session, skill, name=clean_label, presets=presets
    )
    pose = camera_vocab.parse(camera)
    has_master = any(e.entry_type == AssetEntryType.MASTER for e in variant.entries)
    if pose is not None:
        resolved_type, resolved_view = AssetEntryType.VIEW.value, camera_vocab.coarse_view(pose)
    elif view == HERO_VIEW or not has_master:
        resolved_type, resolved_view = AssetEntryType.MASTER.value, None
    else:
        resolved_type = AssetEntryType.SHOT.value
        resolved_view = "detail" if view == "detail" else None
    source = (
        asset_variants_service.find_entry(skill, copy_from_entry_id) if copy_from_entry_id else None
    )
    if source is not None:
        variant = source.variant
        resolved_type, resolved_view = source.entry_type, source.view
    elif entry_type and pose is None:
        resolved_type, resolved_view = entry_type, None
    if generated and source is not None:
        entry = asset_variants_service.file_generated(
            session,
            skill,
            variant,
            asset_id=asset_id,
            entry_type=resolved_type,
            view=resolved_view,
            source_job_id=source_job_id,
            candidate=True,
            camera=source.camera_json,
        )
        asset_variants_service.claim_anchor(session, skill, entry)
        return PropView(skill)
    file = asset_variants_service.file_generated if generated else asset_variants_service.add_entry
    entry = file(
        session,
        skill,
        variant,
        asset_id=asset_id,
        entry_type=resolved_type,
        view=resolved_view,
        source_job_id=source_job_id,
        camera=pose.as_dict() if pose is not None and source is None else None,
    )
    asset_variants_service.claim_anchor(session, skill, entry)
    _promote_master(session, skill)
    return PropView(skill)


def publish_prop(session: Session, *, user_id: str, prop_id: str) -> PropView:
    """Shares a prop to the marketplace — an object, so no portrait consent."""
    skill = owned_prop_skill(session, user_id=user_id, prop_id=prop_id)
    skill_library_service.publish(session, skill=skill, actor_user_id=user_id)
    return PropView(skill)


def withdraw_prop(session: Session, *, user_id: str, prop_id: str) -> PropView:
    skill = owned_prop_skill(session, user_id=user_id, prop_id=prop_id)
    skill_library_service.withdraw(session, skill=skill, actor_user_id=user_id)
    return PropView(skill)


def admin_reference_assets(session: Session, skill: CreationSkill) -> list[dict[str, Any]]:
    """`(asset_id, view, label, url)` per image, for the admin skill view."""
    from app.presenters import media_urls

    if skill.category != CreationSkillCategory.PROP_ASSET:
        return []
    return [
        {
            "asset_id": str(entry["asset_id"]),
            "view": str(entry.get("view") or DEFAULT_VIEW),
            "label": entry.get("label"),
            "url": media_urls.asset_url(session, str(entry["asset_id"])),
        }
        for entry in PropView(skill).reference_assets
        if entry.get("asset_id")
    ]


def _selection_items(params: dict[str, Any], props: list[PropView]) -> dict[str, dict[str, Any]]:
    raw = params.get("prop_ref_selection") or []
    if not isinstance(raw, list):
        return {}
    known = {prop.id for prop in props}
    items: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id") or "")
        if prop_id not in known:
            raise ValidationFailed(
                "所选参考图的道具不在本次选择的道具中。",
                fields={"params.prop_ref_selection": "道具必须同时出现在 prop_ids"},
            )
        items[prop_id] = item
    return items


def apply_prop_refs(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    hints: asset_variants_service.ReferenceHints | None = None,
) -> None:
    """Merges the selected props' references into the job's
    `reference_asset_ids` — after characters and scenes, within the same
    9-slot budget. Each prop contributes its hero plate and the turntable
    view nearest the shot's angle (`default_subset`), ≤2."""
    prop_ids = params.get("prop_ids") or []
    if not isinstance(prop_ids, list) or not prop_ids:
        return
    if len(prop_ids) > MAX_SELECTED_PROPS:
        raise ValidationFailed(
            f"最多选择 {MAX_SELECTED_PROPS} 个道具。",
            fields={"params.prop_ids": f"不能超过 {MAX_SELECTED_PROPS} 个"},
        )
    props = [PropView(owned_prop_skill(session, user_id=user_id, prop_id=pid)) for pid in prop_ids]
    selection = _selection_items(params, props)
    merged = list(params.get("reference_asset_ids") or [])
    for prop in props:
        item = selection.get(prop.id)
        picked = asset_variants_service.select_assets(
            prop.skill,
            variant_id=item.get("variant_id") if item else None,
            asset_ids=list(item.get("asset_ids") or []) if item else None,
            owner=f"道具「{prop.name}」",
            field="params.prop_ref_selection",
            hints=hints,
        )
        for asset_id in picked:
            if asset_id not in merged and len(merged) < MAX_JOB_REFERENCE_ASSETS:
                merged.append(asset_id)
    params["reference_asset_ids"] = merged
