"""Character library and the series that cast them."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.characters import (
    CharacterActionClip,
    CharacterCreateRequest,
    CharacterPublishRequest,
    CharacterReferenceAsset,
    CharacterReferenceAssetUpdateRequest,
    CharacterResponse,
    CharacterUpdateRequest,
    SeriesAddCharacterRequest,
    SeriesCreateRequest,
    SeriesDetailResponse,
    SeriesEpisodeSummary,
    SeriesResponse,
)
from app.domain.characters import service as characters
from app.models import Series, Work, WorkVersion
from app.presenters import media_urls

router = APIRouter(tags=["characters"])


@router.post("/characters", response_model=CharacterResponse, status_code=201)
def create_character(
    payload: CharacterCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.create_character(
        session,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
        voice_description=payload.voice_description,
    )
    session.commit()
    return _character_response(session, character)


@router.get("/characters", response_model=list[CharacterResponse])
def list_characters(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[CharacterResponse]:
    return [
        _character_response(session, character)
        for character in characters.list_characters(session, user_id=user.id)
    ]


@router.get("/characters/{character_id}", response_model=CharacterResponse)
def get_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> CharacterResponse:
    character = characters.get_character(session, user_id=user.id, character_id=character_id)
    return _character_response(session, character)


@router.patch("/characters/{character_id}", response_model=CharacterResponse)
def update_character(
    character_id: str,
    payload: CharacterUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.update_character(
        session,
        user_id=user.id,
        character_id=character_id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
        voice_description=payload.voice_description,
    )
    session.commit()
    return _character_response(session, character)


@router.delete("/characters/{character_id}", status_code=204)
def delete_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> None:
    characters.delete_character(session, user_id=user.id, character_id=character_id)
    session.commit()


@router.patch(
    "/characters/{character_id}/reference-assets/{asset_id}", response_model=CharacterResponse
)
def update_character_reference_asset(
    character_id: str,
    asset_id: str,
    payload: CharacterReferenceAssetUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.update_reference_asset(
        session,
        user_id=user.id,
        character_id=character_id,
        asset_id=asset_id,
        view=payload.view.value if payload.view is not None else None,
        label=payload.label,
    )
    session.commit()
    return _character_response(session, character)


@router.delete(
    "/characters/{character_id}/reference-assets/{asset_id}", response_model=CharacterResponse
)
def delete_character_reference_asset(
    character_id: str,
    asset_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.remove_reference_asset(
        session, user_id=user.id, character_id=character_id, asset_id=asset_id
    )
    session.commit()
    return _character_response(session, character)


@router.post("/characters/{character_id}/publish", response_model=CharacterResponse)
def publish_character(
    character_id: str,
    payload: CharacterPublishRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.publish_character(
        session,
        user_id=user.id,
        character_id=character_id,
        portrait_consent=payload.portrait_consent,
    )
    session.commit()
    return _character_response(session, character)


@router.post("/characters/{character_id}/withdraw", response_model=CharacterResponse)
def withdraw_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.withdraw_character(session, user_id=user.id, character_id=character_id)
    session.commit()
    return _character_response(session, character)


@router.post("/series", response_model=SeriesResponse, status_code=201)
def create_series(
    payload: SeriesCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SeriesResponse:
    series = characters.create_series(
        session,
        user_id=user.id,
        title=payload.title,
        description=payload.description,
        shortform_profile_key=payload.shortform_profile_key,
    )
    session.commit()
    return _series_response(session, series)


@router.get("/series", response_model=list[SeriesResponse])
def list_series(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[SeriesResponse]:
    all_series = characters.list_series(session, user_id=user.id)
    recency = characters.series_recency(session, series_ids=[series.id for series in all_series])

    def sort_key(series: Series) -> dt.datetime:
        info = recency.get(series.id)
        latest_at = info.latest_work.published_at if info and info.latest_work else None
        return latest_at or series.created_at

    ordered = sorted(all_series, key=sort_key, reverse=True)
    return [_series_response(session, series, recency.get(series.id)) for series in ordered]


@router.get("/series/{series_id}", response_model=SeriesDetailResponse)
def get_series(
    series_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> SeriesDetailResponse:
    detail = characters.get_series_detail(session, user_id=user.id, series_id=series_id)
    return SeriesDetailResponse(
        **_series_response(session, detail.series).model_dump(),
        characters=[_character_response(session, c) for c in detail.characters],
        episodes=[_episode_summary(session, work) for work in detail.episodes],
        next_episode_number=detail.next_episode_number,
    )


@router.post("/series/{series_id}/characters", response_model=SeriesResponse)
def add_character_to_series(
    series_id: str,
    payload: SeriesAddCharacterRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SeriesResponse:
    series = characters.add_character_to_series(
        session, user_id=user.id, series_id=series_id, character_id=payload.character_id
    )
    session.commit()
    return _series_response(session, series)


@router.delete("/series/{series_id}/characters/{character_id}", response_model=SeriesResponse)
def remove_character_from_series(
    series_id: str,
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SeriesResponse:
    series = characters.remove_character_from_series(
        session, user_id=user.id, series_id=series_id, character_id=character_id
    )
    session.commit()
    return _series_response(session, series)


def _character_response(session: Session, character: characters.CharacterView) -> CharacterResponse:
    return CharacterResponse(
        id=character.id,
        name=character.name,
        description=character.description,
        reference_assets=[
            CharacterReferenceAsset(
                asset_id=str(entry.get("asset_id")),
                view=str(entry.get("view") or "general"),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in character.reference_assets
            if entry.get("asset_id")
        ],
        action_clips=[
            CharacterActionClip(
                asset_id=str(entry.get("asset_id")),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in character.action_clips
            if entry.get("asset_id")
        ],
        voice_description=character.voice_description,
        status=character.status,
        visibility=character.visibility,
        access_credits=character.access_credits,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


def _series_response(
    session: Session, series: Series, recency: characters.SeriesRecency | None = None
) -> SeriesResponse:
    latest_episode = None
    episode_count = 0
    if recency is not None:
        episode_count = recency.episode_count
        if recency.latest_work is not None:
            latest_episode = _episode_summary(session, recency.latest_work)
    return SeriesResponse(
        id=series.id,
        title=series.title,
        description=series.description,
        shortform_profile_key=series.shortform_profile_key,
        character_ids=list(series.character_ids_json),
        episode_count=episode_count,
        latest_episode=latest_episode,
        created_at=series.created_at,
        updated_at=series.updated_at,
    )


def _episode_summary(session: Session, work: Work) -> SeriesEpisodeSummary:
    version = session.get(WorkVersion, work.current_version_id or "")
    return SeriesEpisodeSummary(
        work_id=work.id,
        episode_number=work.episode_number,
        title=version.title if version else work.id,
        cover_url=media_urls.asset_url(session, version.cover_asset_id) if version else None,
        published_at=work.published_at,
    )
