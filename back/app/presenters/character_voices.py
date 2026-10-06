"""Signed views of a character's voices (P7): the owner's, and the
unlocked one a buyer sees on the skill detail (no clone sample)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas.character_voices import (
    CharacterVoiceView,
    VoiceAttributes,
    VoiceAudioView,
    VoiceParams,
)
from app.domain.characters import voices as voices_service
from app.models import CharacterVoice, CreationSkill
from app.models.enums import VoiceSource
from app.presenters import media_urls


def _audio(session: Session, asset_id: str | None) -> VoiceAudioView | None:
    if not asset_id:
        return None
    return VoiceAudioView(asset_id=asset_id, url=media_urls.asset_url(session, asset_id))


def voice_view(
    session: Session, skill: CreationSkill, voice: CharacterVoice, *, public: bool = False
) -> CharacterVoiceView:
    """`public` is the unlocked view: the clone sample (a real person's
    recording) never leaves the server — jobs reference it by voice id."""
    return CharacterVoiceView(
        id=voice.id,
        name=voice.name,
        description=voice.description,
        source=VoiceSource(voice.source),
        model=voice.model,
        voice=voice.voice,
        params=VoiceParams.model_validate(voice.params_json or {}),
        attributes=VoiceAttributes.model_validate(voice.attributes_json or {}),
        sample=None if public else _audio(session, voice.sample_asset_id),
        preview=_audio(session, voice.preview_asset_id),
        preview_text=voice.preview_text,
        is_default=voice.is_default,
        look_ids=voices_service.bound_look_ids(skill, voice),
        sort_order=voice.sort_order,
        created_at=voice.created_at,
    )
