"""Character library and series payloads."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.common import ApiModel, Timestamped


class CharacterCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=4)
    voice_description: str | None = Field(default=None, max_length=500)


class CharacterUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] | None = Field(default=None, max_length=4)
    voice_description: str | None = Field(default=None, max_length=500)


class CharacterResponse(Timestamped):
    id: str
    name: str
    description: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    reference_asset_urls: list[str] = Field(default_factory=list)
    voice_description: str | None = None


class SeriesCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    shortform_profile_key: str | None = Field(default=None, max_length=64)


class SeriesAddCharacterRequest(ApiModel):
    character_id: str


class SeriesResponse(Timestamped):
    id: str
    title: str
    description: str | None = None
    shortform_profile_key: str | None = None
    character_ids: list[str] = Field(default_factory=list)


class SeriesEpisodeSummary(ApiModel):
    work_id: str
    episode_number: int | None = None
    title: str
    cover_url: str | None = None
    published_at: dt.datetime | None = None


class SeriesDetailResponse(SeriesResponse):
    characters: list[CharacterResponse] = Field(default_factory=list)
    episodes: list[SeriesEpisodeSummary] = Field(default_factory=list)
    next_episode_number: int = 1
