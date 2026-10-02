"""Scene library — a flat, reusable set of settings.

Mirrors `app.domain.characters.service`'s adapter pattern: a scene is no
longer its own table, it is a `CreationSkill` with
`category=SCENE_ASSET` (see `SceneView` below for why callers never need to
know that), stored under `params_json["scene"]`. Unlike a character there is
no roster/`Series` concept — just a name, a description and up to a few
reference stills or clips a script's scene heading can link to
(`app.api.schemas.script.ScriptScene.ref_id`) and a generation job can pull
in via `GenerationParams.scene_ids` (see `apply_scene_refs`, mirroring
`characters.service.apply_character_refs`).

`reference_assets_json` is a structured list of
`{"asset_id", "view", "label", "created_at"}` entries — same shape as a
character skill's `reference_assets` (`characters.service`), so the two
libraries share one picker/UI convention, but with a lighter shot-tag
vocabulary (`establishing`/`detail`/`general`) instead of `ImageAssetKind`'s
fixed character views.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as asset_variants_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill
from app.models.enums import (
    AssetEntryType,
    CreationSkillCategory,
    MediaType,
)

# A flat `reference_asset_ids` list (create/PATCH) fills one variant — the
# per-variant entry cap (`asset_variants.service`); variants hold the rest.
MAX_REFERENCE_ASSETS = asset_variants_service.MAX_ENTRIES_PER_VARIANT
MAX_DEFAULT_JOB_REFERENCES = asset_variants_service.MAX_DEFAULT_SCENE_REFERENCES
MASTER_VIEW = "establishing"
# Mirrors GenerationParams.reference_asset_ids in jobs.py — kept here too so a
# validation error names the right limit before a job ever reaches the API
# schema, same rationale as `characters.service.MAX_JOB_REFERENCE_ASSETS`.
MAX_JOB_REFERENCE_ASSETS = 9
MAX_SELECTED_SCENES = 4

DEFAULT_VIEW = "general"

# Sub-key inside `CreationSkill.params_json` a scene skill's structured data
# lives under — mirrors `characters.service.CHARACTER_PARAMS_KEY`.
SCENE_PARAMS_KEY = "scene"

_REFERENCE_MEDIA_TYPES = (MediaType.IMAGE, MediaType.VIDEO)


@dataclass(slots=True)
class SceneView:
    """A scene-shaped projection of the underlying `CreationSkill` row.

    Every caller (`api/v1/scenes.py`, `apply_scene_refs`,
    `app.workflows.nodes`) keeps talking about "scenes" — name, description,
    reference assets — instead of learning the generic skill schema.
    """

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
        """The P0-shaped projection (`asset_variants.service.project`): the
        master plate first, tagged `establishing`."""
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
    """A shallow *copy* of the scene's nested payload — never the live dict
    stored inside `skill.params_json`. See `characters.service._payload` for
    why this must never hand back the live reference."""
    raw = skill.params_json.get(SCENE_PARAMS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _set_payload(skill: CreationSkill, payload: dict[str, Any]) -> None:
    skill.params_json = {**skill.params_json, SCENE_PARAMS_KEY: payload}


def _short_description(description: str | None) -> str:
    return (description or "").strip()[:300]


def _owned_scene_skill(session: Session, *, user_id: str, scene_id: str) -> CreationSkill:
    skill = session.get(CreationSkill, scene_id)
    # Same 404 for missing, someone else's, or a non-scene skill — existence
    # (and category) is not confirmed.
    if (
        skill is None
        or skill.owner_user_id != user_id
        or skill.category != CreationSkillCategory.SCENE_ASSET
    ):
        raise NotFound("场景不存在。")
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
                "场景参考素材必须是图片或视频。", fields={"reference_asset_ids": "必须是图片或视频"}
            )
    return deduped


def create_scene(
    session: Session,
    *,
    user_id: str,
    name: str,
    description: str | None,
    reference_asset_ids: list[str],
) -> SceneView:
    refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
    clean_description = (description or "").strip() or None
    skill = skill_library_service.create(
        session,
        owner_user_id=user_id,
        title=name.strip(),
        description=_short_description(clean_description),
        category=CreationSkillCategory.SCENE_ASSET,
        params_json={
            SCENE_PARAMS_KEY: {
                "description": clean_description,
                "reference_assets": [],
            }
        },
        cover_asset_id=None,
    )
    asset_variants_service.ensure_default(session, skill)
    asset_variants_service.set_members(session, skill, refs)
    _promote_master(session, skill)
    return SceneView(skill)


def list_scenes(session: Session, *, user_id: str) -> list[SceneView]:
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == user_id,
            CreationSkill.category == CreationSkillCategory.SCENE_ASSET,
        )
        .order_by(CreationSkill.created_at.desc())
    )
    return [SceneView(skill) for skill in session.scalars(stmt)]


def get_scene(session: Session, *, user_id: str, scene_id: str) -> SceneView:
    return SceneView(_owned_scene_skill(session, user_id=user_id, scene_id=scene_id))


def update_scene(
    session: Session,
    *,
    user_id: str,
    scene_id: str,
    name: str | None = None,
    description: str | None = None,
    reference_asset_ids: list[str] | None = None,
) -> SceneView:
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    payload = _payload(skill)
    if name is not None:
        skill.title = name.strip()
    if description is not None:
        clean = description.strip() or None
        payload["description"] = clean
        skill.description = _short_description(clean)
    # Before the reference edit: `set_members` re-syncs the JSON mirror on
    # top of this payload, and writing the payload afterwards would clobber it.
    _set_payload(skill, payload)
    if reference_asset_ids is not None:
        refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
        asset_variants_service.set_members(session, skill, refs)
        _promote_master(session, skill)
    # Editing a shared skill's content withdraws it from the marketplace
    # until the owner re-publishes — same rule as any other `CreationSkill`
    # (`skill_library.service.update`).
    skill_library_service.withdraw_after_edit(session, skill)
    session.flush()
    return SceneView(skill)


def delete_scene(session: Session, *, user_id: str, scene_id: str) -> None:
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    skill_library_service.delete(session, skill=skill, actor_user_id=user_id)


# ---- Per-image reference asset management --------------------------------


def master_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The master plate among projected entries: the first `establishing`
    one (the projection lists the anchor first, tagged `establishing`), else
    the oldest unlabelled one."""
    for entry in entries:
        if entry.get("view") == MASTER_VIEW:
            return entry
    return next((e for e in entries if not (e.get("label") or "").strip()), None)


def _promote_master(session: Session, skill: CreationSkill) -> None:
    """Keeps P0's "a scene always has a master plate" rule on the tables:
    with no anchor yet, the default variant's first image becomes the
    `master` and the card's anchor."""
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
    asset_variants_service.set_anchor(session, skill, first)


def default_reference_asset_ids(scene: SceneView, variant_id: str | None = None) -> list[str]:
    """What a job gets for this scene when the caller picked no images: the
    default (or `variant_id`'s) master plate plus its next shot, falling
    back to the card's anchor — see `asset_variants.service.default_subset`.
    Other variants (黄昏/战损…) only go in when picked: a dusk plate must not
    tint a daytime scene."""
    variant = asset_variants_service.find_variant(scene.skill, variant_id) if variant_id else None
    return asset_variants_service.default_subset(scene.skill, variant)


def _selection_items(params: dict[str, Any], scenes: list[SceneView]) -> dict[str, dict[str, Any]]:
    """`scene_ref_selection` keyed by scene id; every named scene must be
    one of this job's `scene_ids`."""
    raw = params.get("scene_ref_selection") or []
    if not isinstance(raw, list):
        return {}
    known = {scene.id for scene in scenes}
    items: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        scene_id = str(item.get("scene_id") or "")
        if scene_id not in known:
            raise ValidationFailed(
                "所选参考图的场景不在本次选择的场景中。",
                fields={"params.scene_ref_selection": "场景必须同时出现在 scene_ids"},
            )
        items[scene_id] = item
    return items


def append_reference_asset(
    session: Session,
    *,
    user_id: str,
    scene_id: str,
    asset_id: str,
    view: str = DEFAULT_VIEW,
    label: str | None = None,
    presets: dict[str, Any] | None = None,
    source_job_id: str | None = None,
    variant_id: str | None = None,
    generated: bool = False,
) -> SceneView:
    """Files one image under a variant — the P0 `(view, label)` shape,
    translated: `variant_id` (a variant of this card) wins, else `presets` (or
    a `label`) pick the variant (created on first use); a stale `variant_id`
    falls back to them. `establishing` — or being a non-default variant's
    first image — makes it that variant's master plate (the previous master
    becomes a shot); anything else accumulates as a shot up to the variant's
    cap (422 beyond it). With no anchor yet the default variant's first image
    becomes master + anchor.

    `generated` (a job's write-back) never displaces: a master for a
    variant that already has an approved one is kept as a candidate
    (`asset_variants.service.file_generated`).

    Called by the scene library UI and by
    `app.workflows.nodes.execute_asset_output_link`.
    """
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    _validate_reference_assets(session, user_id=user_id, asset_ids=[asset_id])
    clean_label = (label or "").strip() or None
    variant = (
        asset_variants_service.find_variant(skill, variant_id) if variant_id else None
    ) or asset_variants_service.find_or_create_variant(
        session, skill, name=clean_label, presets=presets
    )
    has_master = any(e.entry_type == AssetEntryType.MASTER for e in variant.entries)
    positional = view in ("detail", "reverse")
    if view == MASTER_VIEW or (not has_master and not variant.is_default and not positional):
        if not generated:
            for previous in variant.entries:
                if previous.entry_type == AssetEntryType.MASTER and previous.asset_id != asset_id:
                    previous.entry_type = AssetEntryType.SHOT.value
        entry_type, entry_view = AssetEntryType.MASTER.value, None
    else:
        entry_type = AssetEntryType.SHOT.value
        entry_view = view if positional else None
    file = asset_variants_service.file_generated if generated else asset_variants_service.add_entry
    entry = file(
        session,
        skill,
        variant,
        asset_id=asset_id,
        entry_type=entry_type,
        view=entry_view,
        source_job_id=source_job_id,
    )
    if (
        entry_type == AssetEntryType.MASTER
        and asset_variants_service.is_approved(entry)
        and (asset_variants_service.anchor(skill) is None or variant.is_default)
    ):
        asset_variants_service.set_anchor(session, skill, entry)
    _promote_master(session, skill)
    return SceneView(skill)


def update_reference_asset(
    session: Session,
    *,
    user_id: str,
    scene_id: str,
    asset_id: str,
    view: str | None = None,
    label: str | None = None,
) -> SceneView:
    """The P0 per-image edit: `view=establishing` makes it the master plate,
    a new `label` moves it to the variant of that name (blank → default)."""
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    entries = SceneView(skill).reference_assets
    projected = next((e for e in entries if e.get("asset_id") == asset_id), None)
    if projected is None:
        raise NotFound("参考素材不存在。")
    master = master_entry(entries)
    new_view = view if view is not None else str(projected.get("view") or DEFAULT_VIEW)
    new_label = label.strip() or None if label is not None else projected.get("label")
    was_anchor = bool(projected.get("is_anchor")) or projected is master
    asset_variants_service.remove_asset(session, skill, asset_id)
    if was_anchor:
        asset_variants_service.set_anchor(session, skill, None)
    append_reference_asset(
        session,
        user_id=user_id,
        scene_id=scene_id,
        asset_id=asset_id,
        view=MASTER_VIEW if was_anchor and view is None else new_view,
        label=new_label,
    )
    return SceneView(skill)


def remove_reference_asset(
    session: Session, *, user_id: str, scene_id: str, asset_id: str
) -> SceneView:
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    asset_variants_service.remove_asset(session, skill, asset_id)
    _promote_master(session, skill)
    return SceneView(skill)


def publish_scene(session: Session, *, user_id: str, scene_id: str) -> SceneView:
    """Shares a scene to the skill marketplace, for other creators to use.

    Unlike a character, a scene depicts a setting rather than a person, so
    it needs no portrait/likeness consent step — this is a thin pass-through
    to `skill_library.publish`.
    """
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    skill_library_service.publish(session, skill=skill, actor_user_id=user_id)
    return SceneView(skill)


def withdraw_scene(session: Session, *, user_id: str, scene_id: str) -> SceneView:
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    skill_library_service.withdraw(session, skill=skill, actor_user_id=user_id)
    return SceneView(skill)


# ---- Admin/moderation projection -----------------------------------------


def admin_reference_assets(session: Session, skill: CreationSkill) -> list[dict[str, Any]]:
    """`(asset_id, view, label, url)` for every reference image on a scene
    skill, for `CreationSkillAdminView`. Mirrors
    `characters.service.admin_reference_assets`; non-scene skills have
    nothing to project."""
    from app.presenters import media_urls

    if skill.category != CreationSkillCategory.SCENE_ASSET:
        return []
    return [
        {
            "asset_id": str(entry["asset_id"]),
            "view": str(entry.get("view") or DEFAULT_VIEW),
            "label": entry.get("label"),
            "url": media_urls.asset_url(session, str(entry["asset_id"])),
        }
        for entry in SceneView(skill).reference_assets
        if entry.get("asset_id")
    ]


# ---- Generation wiring -----------------------------------------------------


def apply_scene_refs(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    hints: asset_variants_service.ReferenceHints | None = None,
) -> None:
    """Merges the selected scenes' reference assets into job params.

    Mirrors `characters.service.apply_character_refs`; called right after it
    in `jobs/service.py::submit` so both share the same `reference_asset_ids`
    budget (`MAX_JOB_REFERENCE_ASSETS`) rather than each independently
    assuming the full 9 slots are theirs.
    """
    scene_ids = params.get("scene_ids") or []
    if not isinstance(scene_ids, list) or not scene_ids:
        return
    if len(scene_ids) > MAX_SELECTED_SCENES:
        raise ValidationFailed(
            f"最多选择 {MAX_SELECTED_SCENES} 个场景。",
            fields={"params.scene_ids": f"不能超过 {MAX_SELECTED_SCENES} 个"},
        )

    scenes = [
        SceneView(_owned_scene_skill(session, user_id=user_id, scene_id=sid)) for sid in scene_ids
    ]
    selection = _selection_items(params, scenes)

    merged_refs = list(params.get("reference_asset_ids") or [])
    for scene in scenes:
        item = selection.get(scene.id)
        picked = asset_variants_service.select_assets(
            scene.skill,
            variant_id=item.get("variant_id") if item else None,
            asset_ids=list(item.get("asset_ids") or []) if item else None,
            owner=f"场景「{scene.name}」",
            field="params.scene_ref_selection",
            hints=hints,
        )
        for asset_id in picked:
            if asset_id not in merged_refs and len(merged_refs) < MAX_JOB_REFERENCE_ASSETS:
                merged_refs.append(asset_id)
    params["reference_asset_ids"] = merged_refs
