"""A character card's voices (P7, `/v1/characters/{id}/voices…`)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.api.schemas.asset_variants import CustomAttribute
from app.api.schemas.common import ApiModel
from app.domain.asset_variants.service import MAX_CUSTOM_ATTRIBUTES
from app.domain.characters.voices import (
    MAX_PREVIEW_TEXT_LEN,
    MAX_VOICE_EMOTION_LEN,
    MAX_VOICE_NAME_LEN,
)
from app.domain.image_assets.vocabulary import AgeStage
from app.models.enums import QualityTier, VoiceSource
from app.providers.model_catalog import VOICE_SPEED_RANGE

VoiceUse = Literal["dialogue", "inner_monologue", "narration"]


class VoiceParams(ApiModel):
    """Only the knobs the voice's model takes (`voice_capabilities`)."""

    speed: float | None = Field(default=None, ge=VOICE_SPEED_RANGE[0], le=VOICE_SPEED_RANGE[1])
    emotion: str | None = Field(default=None, max_length=MAX_VOICE_EMOTION_LEN)


class VoiceAttributes(ApiModel):
    age_stage: AgeStage | None = None
    emotion: str | None = Field(default=None, max_length=MAX_VOICE_EMOTION_LEN)
    use: VoiceUse | None = None
    custom: list[CustomAttribute] = Field(default_factory=list, max_length=MAX_CUSTOM_ATTRIBUTES)


class VoiceAudioView(ApiModel):
    asset_id: str
    url: str | None = None


class CharacterVoiceView(ApiModel):
    id: str
    name: str
    description: str | None = None
    source: VoiceSource
    model: str | None = None
    voice: str | None = None
    params: VoiceParams = Field(default_factory=VoiceParams)
    attributes: VoiceAttributes = Field(default_factory=VoiceAttributes)
    sample: VoiceAudioView | None = None
    preview: VoiceAudioView | None = None
    preview_text: str | None = None
    is_default: bool = False
    # Looks of this card that speak with this voice.
    look_ids: list[str] = Field(default_factory=list)
    sort_order: int = 0
    created_at: dt.datetime | None = None


class CharacterVoiceCreateRequest(ApiModel):
    """A new voice; with `derived_from`, unspecified fields come from that
    voice and an auto edge records what changed."""

    name: str = Field(min_length=1, max_length=MAX_VOICE_NAME_LEN)
    description: str | None = Field(default=None, max_length=500)
    source: VoiceSource | None = None
    model: str | None = Field(default=None, max_length=200)
    voice: str | None = Field(default=None, max_length=60)
    params: VoiceParams | None = None
    attributes: VoiceAttributes | None = None
    sample_asset_id: str | None = Field(default=None, max_length=40)
    preview_text: str | None = Field(default=None, max_length=MAX_PREVIEW_TEXT_LEN)
    look_ids: list[str] | None = Field(default=None, max_length=48)
    derived_from: str | None = Field(default=None, max_length=40)


class CharacterVoiceUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_VOICE_NAME_LEN)
    description: str | None = Field(default=None, max_length=500)
    source: VoiceSource | None = None
    model: str | None = Field(default=None, max_length=200)
    voice: str | None = Field(default=None, max_length=60)
    params: VoiceParams | None = None
    attributes: VoiceAttributes | None = None
    sample_asset_id: str | None = Field(default=None, max_length=40)
    preview_text: str | None = Field(default=None, max_length=MAX_PREVIEW_TEXT_LEN)
    look_ids: list[str] | None = Field(default=None, max_length=48)
    make_default: bool = False


class VoicePreviewRequest(ApiModel):
    # Defaults to the voice's own preview text (else a stock sentence).
    text: str | None = Field(default=None, min_length=1, max_length=MAX_PREVIEW_TEXT_LEN)
    quality_tier: QualityTier = QualityTier.STANDARD
    # `true` (the default) only prices; `false` submits one job.
    dry_run: bool = True


class VoicePreviewResponse(ApiModel):
    credits: int
    available_credits: int
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool
    job_id: str | None = None
    replayed: bool = False


class VoiceMatchRequest(ApiModel):
    # Defaults to the card's own 音色描述.
    voice_description: str | None = Field(default=None, max_length=500)


class VoiceMatchResponse(ApiModel):
    """A proposal only — nothing is saved."""

    model: str
    model_label: str
    voice: str
    params: VoiceParams = Field(default_factory=VoiceParams)
    reason: str = ""
