"""What each reference image of a job *is* — written at submit into
`params["reference_labels"]` for the prompt's reference legend
(`prompt_builder.reference_legend`).

Derived from the job's own characters/scenes (picked or targeted) rather
than tracked through `apply_character_refs`/`apply_scene_refs`, so an
explicitly attached sheet of the target character is named too.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.errors import NotFound
from app.domain.scenes import service as scenes_service
from app.models.enums import CharacterViewAngle

_VIEW_NAMES = {
    CharacterViewAngle.FRONT.value: "设定图",
    CharacterViewAngle.SIDE.value: "侧面",
    CharacterViewAngle.BACK.value: "背面",
}


def _character_label(name: str, entry: dict[str, Any]) -> str:
    label = str(entry.get("label") or "").strip()
    view = str(entry.get("view") or "")
    if label and view in _VIEW_NAMES and view != CharacterViewAngle.FRONT.value:
        return f"角色「{name}」·{label}·{_VIEW_NAMES[view]}"
    if label:
        return f"角色「{name}」·{label}"
    return f"角色「{name}」{_VIEW_NAMES.get(view, '参考图')}"


def _scene_label(name: str, entry: dict[str, Any], *, is_master: bool) -> str:
    label = str(entry.get("label") or "").strip()
    if label:
        return f"场景「{name}」·{label}"
    return f"场景「{name}」{'主图' if is_master else '参考图'}"


def _ids(params: dict[str, Any], list_key: str, target_key: str) -> list[str]:
    raw = params.get(list_key)
    ids = [str(item) for item in raw] if isinstance(raw, list) else []
    target = params.get(target_key)
    if target and str(target) not in ids:
        ids.append(str(target))
    return ids


def label_references(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """Writes `params["reference_labels"]` for every reference this job's
    characters/scenes can name; leaves it unset when there are none."""
    wanted = {str(asset_id) for asset_id in params.get("reference_asset_ids") or []}
    if not wanted:
        return
    labels: dict[str, str] = {}
    for character_id in _ids(params, "character_ids", "target_character_id"):
        try:
            character = characters_service.get_character(
                session, user_id=user_id, character_id=character_id
            )
        except NotFound:
            continue
        for entry in character.reference_assets:
            asset_id = str(entry.get("asset_id") or "")
            if asset_id in wanted and asset_id not in labels:
                labels[asset_id] = _character_label(character.name, entry)[:60]
    for scene_id in _ids(params, "scene_ids", "target_scene_id"):
        try:
            scene = scenes_service.get_scene(session, user_id=user_id, scene_id=scene_id)
        except NotFound:
            continue
        entries = scene.reference_assets
        master = scenes_service.master_entry(entries)
        for entry in entries:
            asset_id = str(entry.get("asset_id") or "")
            if asset_id in wanted and asset_id not in labels:
                labels[asset_id] = _scene_label(scene.name, entry, is_master=entry is master)[:60]
    if labels:
        params["reference_labels"] = [
            {"asset_id": asset_id, "label": label} for asset_id, label in labels.items()
        ]
