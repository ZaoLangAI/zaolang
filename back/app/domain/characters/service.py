"""Character library and the series that cast them.

A character is a reusable cast member: a name, up to a few reference images
and a text voice description. A series is a named cast roster plus the
episode numbering that published `Work` rows carry, so a creator can ask for
"the same face and voice" on episode two without retyping anything.

Nothing here talks to a real TTS or face-consistency provider — those do not
exist yet (see `back/app/providers/fake.py`). `voice_description` and the
reference images are carried through to the job so a real provider has
something to match against once one is wired in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.models import Asset, Character, Series, Work
from app.models.enums import MediaType

MAX_REFERENCE_ASSETS = 4
# Mirrors GenerationParams.reference_asset_ids / character_ids in jobs.py —
# kept here too so a validation error names the right limit before a job ever
# reaches the API schema.
MAX_JOB_REFERENCE_ASSETS = 6
MAX_SELECTED_CHARACTERS = 4


def _owned_character(session: Session, *, user_id: str, character_id: str) -> Character:
    character = session.get(Character, character_id)
    # Same 404 for missing and someone else's: existence is not confirmed.
    if character is None or character.owner_user_id != user_id:
        raise NotFound("角色不存在。")
    return character


def _owned_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = session.get(Series, series_id)
    if series is None or series.owner_user_id != user_id:
        raise NotFound("系列不存在。")
    return series


def _validate_reference_assets(
    session: Session, *, user_id: str, asset_ids: list[str]
) -> list[str]:
    deduped = list(dict.fromkeys(asset_ids))
    if len(deduped) > MAX_REFERENCE_ASSETS:
        raise ValidationFailed(
            f"参考图最多 {MAX_REFERENCE_ASSETS} 张。",
            fields={"reference_asset_ids": f"不能超过 {MAX_REFERENCE_ASSETS} 张"},
        )
    for asset_id in deduped:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_user_id != user_id:
            raise NotFound("参考图不存在。")
        if asset.media_type != MediaType.IMAGE:
            raise ValidationFailed(
                "角色参考素材必须是图片。", fields={"reference_asset_ids": "必须是图片"}
            )
    return deduped


# ---- Character CRUD ----------------------------------------------------


def create_character(
    session: Session,
    *,
    user_id: str,
    name: str,
    description: str | None,
    reference_asset_ids: list[str],
    voice_description: str | None,
) -> Character:
    refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
    character = Character(
        owner_user_id=user_id,
        name=name.strip(),
        description=(description or "").strip() or None,
        reference_asset_ids_json=refs,
        voice_description=(voice_description or "").strip() or None,
    )
    session.add(character)
    session.flush()
    return character


def list_characters(session: Session, *, user_id: str) -> list[Character]:
    stmt = (
        select(Character)
        .where(Character.owner_user_id == user_id)
        .order_by(Character.created_at.desc())
    )
    return list(session.scalars(stmt))


def get_character(session: Session, *, user_id: str, character_id: str) -> Character:
    return _owned_character(session, user_id=user_id, character_id=character_id)


def update_character(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    name: str | None = None,
    description: str | None = None,
    reference_asset_ids: list[str] | None = None,
    voice_description: str | None = None,
) -> Character:
    character = _owned_character(session, user_id=user_id, character_id=character_id)
    if name is not None:
        character.name = name.strip()
    if description is not None:
        character.description = description.strip() or None
    if reference_asset_ids is not None:
        character.reference_asset_ids_json = _validate_reference_assets(
            session, user_id=user_id, asset_ids=reference_asset_ids
        )
    if voice_description is not None:
        character.voice_description = voice_description.strip() or None
    session.flush()
    return character


def delete_character(session: Session, *, user_id: str, character_id: str) -> None:
    character = _owned_character(session, user_id=user_id, character_id=character_id)
    # Leaving a stale id in a series' roster would surface as a silent no-op
    # the next time the cast is resolved, so the roster is cleaned up here.
    for series in session.scalars(select(Series).where(Series.owner_user_id == user_id)):
        if character.id in series.character_ids_json:
            series.character_ids_json = [
                cid for cid in series.character_ids_json if cid != character.id
            ]
    session.delete(character)
    session.flush()


# ---- Series CRUD --------------------------------------------------------


def create_series(
    session: Session,
    *,
    user_id: str,
    title: str,
    description: str | None,
    shortform_profile_key: str | None,
) -> Series:
    series = Series(
        owner_user_id=user_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        shortform_profile_key=shortform_profile_key,
        character_ids_json=[],
    )
    session.add(series)
    session.flush()
    return series


def list_series(session: Session, *, user_id: str) -> list[Series]:
    stmt = select(Series).where(Series.owner_user_id == user_id).order_by(Series.created_at.desc())
    return list(session.scalars(stmt))


@dataclass(slots=True)
class SeriesDetail:
    series: Series
    characters: list[Character]
    episodes: list[Work]
    next_episode_number: int


def get_series_detail(session: Session, *, user_id: str, series_id: str) -> SeriesDetail:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    characters = [
        character
        for character in (session.get(Character, cid) for cid in series.character_ids_json)
        if character is not None
    ]
    episodes = list(
        session.scalars(
            select(Work)
            .where(Work.series_id == series_id)
            .order_by(Work.episode_number.asc().nulls_last())
        )
    )
    return SeriesDetail(
        series=series,
        characters=characters,
        episodes=episodes,
        next_episode_number=_next_episode_number(episodes),
    )


def _next_episode_number(episodes: list[Work]) -> int:
    numbers = [work.episode_number for work in episodes if work.episode_number is not None]
    return max(numbers, default=0) + 1


def add_character_to_series(
    session: Session, *, user_id: str, series_id: str, character_id: str
) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    _owned_character(session, user_id=user_id, character_id=character_id)
    if character_id not in series.character_ids_json:
        series.character_ids_json = [*series.character_ids_json, character_id]
        session.flush()
    return series


def remove_character_from_series(
    session: Session, *, user_id: str, series_id: str, character_id: str
) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    series.character_ids_json = [cid for cid in series.character_ids_json if cid != character_id]
    session.flush()
    return series


# ---- Generation + publish wiring ----------------------------------------


def apply_character_refs(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """Merges the selected cast's reference images and voice hints into job params.

    Called right before a job is priced and persisted (`jobs/service.py`), so
    the merged `reference_asset_ids` becomes part of what the pipeline
    actually forwards to the provider. Explicitly-uploaded reference images
    keep their slots; character references fill whatever room is left.
    """
    character_ids = params.get("character_ids") or []
    if not character_ids:
        return
    if len(character_ids) > MAX_SELECTED_CHARACTERS:
        raise ValidationFailed(
            f"最多选择 {MAX_SELECTED_CHARACTERS} 个角色。",
            fields={"params.character_ids": f"不能超过 {MAX_SELECTED_CHARACTERS} 个"},
        )

    characters = [
        _owned_character(session, user_id=user_id, character_id=cid) for cid in character_ids
    ]

    merged_refs = list(params.get("reference_asset_ids") or [])
    for character in characters:
        for asset_id in character.reference_asset_ids_json:
            if asset_id not in merged_refs and len(merged_refs) < MAX_JOB_REFERENCE_ASSETS:
                merged_refs.append(asset_id)
    params["reference_asset_ids"] = merged_refs

    extra = dict(params.get("extra") or {})
    extra["character_voice_profiles"] = [
        {
            "character_id": character.id,
            "name": character.name,
            "voice_description": character.voice_description,
        }
        for character in characters
        if character.voice_description
    ]
    params["extra"] = extra


def assign_episode(
    session: Session,
    *,
    user_id: str,
    work: Work,
    series_id: str | None,
    episode_number: int | None,
) -> None:
    """Called at publish time. A work with no chosen series stays standalone."""
    if not series_id:
        return

    series = _owned_series(session, user_id=user_id, series_id=series_id)
    if episode_number is None:
        episode_number = get_series_detail(
            session, user_id=user_id, series_id=series_id
        ).next_episode_number

    clash = session.scalar(
        select(Work).where(Work.series_id == series.id, Work.episode_number == episode_number)
    )
    if clash is not None:
        raise Conflict(f"第 {episode_number} 集已经存在。")

    work.series_id = series.id
    work.episode_number = episode_number
