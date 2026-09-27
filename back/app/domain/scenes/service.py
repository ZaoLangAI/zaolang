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

from app.domain.errors import NotFound, ValidationFailed
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill
from app.models.base import utcnow
from app.models.enums import (
    CreationSkillCategory,
    MediaType,
)

MAX_REFERENCE_ASSETS = 4
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
        return list(_reference_assets(self.skill))

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


def _reference_assets(skill: CreationSkill) -> list[dict[str, Any]]:
    """Copies of each reference-asset entry — see `characters.service.
    _reference_assets` for the dirty-tracking bug this mirrors avoiding."""
    raw = _payload(skill).get("reference_assets")
    return (
        [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
    )


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


def _entries_from_flat_ids(asset_ids: list[str]) -> list[dict[str, Any]]:
    now = utcnow().isoformat()
    return [
        {"asset_id": asset_id, "view": DEFAULT_VIEW, "label": None, "created_at": now}
        for asset_id in asset_ids
    ]


# ---- Scene CRUD (adapter over the skill library) ------------------------


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
                "reference_assets": _entries_from_flat_ids(refs),
            }
        },
        cover_asset_id=None,
    )
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
    if reference_asset_ids is not None:
        refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
        payload["reference_assets"] = _entries_from_flat_ids(refs)
    _set_payload(skill, payload)
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


def append_reference_asset(
    session: Session,
    *,
    user_id: str,
    scene_id: str,
    asset_id: str,
    view: str = DEFAULT_VIEW,
    label: str | None = None,
) -> SceneView:
    """Adds (or replaces) one shot's reference image.

    Called both by the scene library UI's per-image upload and by
    `app.workflows.nodes.execute_asset_output_link` when a generation job's
    output is auto-attached.
    """
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    _validate_reference_assets(session, user_id=user_id, asset_ids=[asset_id])
    payload = _payload(skill)
    entries = [e for e in _reference_assets(skill) if e.get("asset_id") != asset_id]
    entries.append(
        {
            "asset_id": asset_id,
            "view": view,
            "label": (label or "").strip() or None,
            "created_at": utcnow().isoformat(),
        }
    )
    if len(entries) > MAX_REFERENCE_ASSETS:
        entries = entries[-MAX_REFERENCE_ASSETS:]
    payload["reference_assets"] = entries
    _set_payload(skill, payload)
    session.flush()
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
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    payload = _payload(skill)
    entries = _reference_assets(skill)
    found = False
    for entry in entries:
        if entry.get("asset_id") == asset_id:
            found = True
            if view is not None:
                entry["view"] = view
            if label is not None:
                entry["label"] = label.strip() or None
    if not found:
        raise NotFound("参考素材不存在。")
    payload["reference_assets"] = entries
    _set_payload(skill, payload)
    session.flush()
    return SceneView(skill)


def remove_reference_asset(
    session: Session, *, user_id: str, scene_id: str, asset_id: str
) -> SceneView:
    skill = _owned_scene_skill(session, user_id=user_id, scene_id=scene_id)
    payload = _payload(skill)
    payload["reference_assets"] = [
        e for e in _reference_assets(skill) if e.get("asset_id") != asset_id
    ]
    _set_payload(skill, payload)
    session.flush()
    return SceneView(skill)


# ---- Sharing: publish a scene to the skill marketplace -------------------


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


def apply_scene_refs(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
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

    merged_refs = list(params.get("reference_asset_ids") or [])
    for scene in scenes:
        for asset_id in scene.reference_asset_ids:
            if asset_id not in merged_refs and len(merged_refs) < MAX_JOB_REFERENCE_ASSETS:
                merged_refs.append(asset_id)
    params["reference_asset_ids"] = merged_refs
