"""A character card's voices (P7): `/v1/characters/{id}/voices…`.

Owner-only (someone else's card or voice is a 404). Voices are graph
metadata, not published content: a write neither withdraws a published card
nor goes through moderation. `:preview` prices / submits one
`audio_generation` job whose output becomes the voice's preview
(`jobs.completion._land_voice_preview`); `voices:match` proposes a preset
voice for the card's 音色描述 and saves nothing.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import character_profile
from app.api import rate_limit
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, client_identity, rate_limited
from app.api.schemas.character_voices import (
    CharacterVoiceCreateRequest,
    CharacterVoiceUpdateRequest,
    CharacterVoiceView,
    VoiceMatchRequest,
    VoiceMatchResponse,
    VoiceParams,
    VoicePreviewRequest,
    VoicePreviewResponse,
)
from app.api.schemas.jobs import GenerationParams
from app.domain.characters import service as characters_service
from app.domain.characters import voices as voices_service
from app.domain.credits import service as credits_service
from app.domain.errors import InsufficientCredits, SpendLimitExceeded, ValidationFailed
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import service as jobs_service
from app.models import CreationSkill, GenerationJob
from app.models.base import new_id
from app.models.enums import Operation
from app.presenters import character_voices as presenter
from app.providers import model_catalog

router = APIRouter(tags=["character-voices"])

Write = Annotated[None, Depends(rate_limited("authenticated_write"))]
Read = Annotated[None, Depends(rate_limited("public_read"))]


def _card(session: Session, user_id: str, card_id: str) -> tuple[CreationSkill, Any]:
    character = characters_service.get_character(session, user_id=user_id, character_id=card_id)
    return character.skill, character


def _fields(payload: Any, *, name: str) -> voices_service.VoiceFields:
    return voices_service.VoiceFields(
        name=name,
        source=str(payload.source) if payload.source else "",
        description=payload.description,
        model=payload.model,
        voice=payload.voice,
        params=payload.params.model_dump(exclude_none=True) if payload.params else None,
        attributes=payload.attributes.model_dump(exclude_none=True) if payload.attributes else None,
        sample_asset_id=payload.sample_asset_id,
        preview_text=payload.preview_text,
    )


@router.get("/characters/{card_id}/voices", response_model=list[CharacterVoiceView])
def list_voices(
    card_id: str, user: CurrentUser, session: DbSession, _: Read
) -> list[CharacterVoiceView]:
    skill, _character = _card(session, user.id, card_id)
    return [
        presenter.voice_view(session, skill, voice)
        for voice in voices_service.voices(session, skill)
    ]


@router.post("/characters/{card_id}/voices", response_model=CharacterVoiceView, status_code=201)
def create_voice(
    card_id: str,
    payload: CharacterVoiceCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Write,
) -> CharacterVoiceView:
    skill, _character = _card(session, user.id, card_id)
    fields = _fields(payload, name=payload.name)
    if payload.derived_from:
        source = voices_service.find_voice(session, skill, payload.derived_from)
        voice, _edge = voices_service.derive_voice(session, skill, source, fields)
    else:
        if not fields.source:
            raise ValidationFailed("请选择音色来源。", fields={"source": "不能为空"})
        voice = voices_service.create_voice(session, skill, fields)
    if payload.look_ids is not None:
        voices_service.bind_looks(session, skill, voice, payload.look_ids)
    session.commit()
    return presenter.voice_view(session, skill, voice)


@router.patch("/characters/{card_id}/voices/{voice_id}", response_model=CharacterVoiceView)
def update_voice(
    card_id: str,
    voice_id: str,
    payload: CharacterVoiceUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Write,
) -> CharacterVoiceView:
    skill, _character = _card(session, user.id, card_id)
    voice = voices_service.find_voice(session, skill, voice_id)
    voices_service.update_voice(
        session,
        skill,
        voice,
        name=payload.name,
        description=payload.description,
        source=str(payload.source) if payload.source else None,
        model=payload.model,
        voice_id=payload.voice,
        params=payload.params.model_dump(exclude_none=True) if payload.params else None,
        attributes=payload.attributes.model_dump(exclude_none=True) if payload.attributes else None,
        sample_asset_id=payload.sample_asset_id,
        preview_text=payload.preview_text,
        make_default=payload.make_default,
    )
    if payload.look_ids is not None:
        voices_service.bind_looks(session, skill, voice, payload.look_ids)
    session.commit()
    return presenter.voice_view(session, skill, voice)


@router.delete("/characters/{card_id}/voices/{voice_id}", status_code=204)
def delete_voice(
    card_id: str, voice_id: str, user: CurrentUser, session: DbSession, _: Write
) -> Response:
    skill, _character = _card(session, user.id, card_id)
    voices_service.delete_voice(session, skill, voices_service.find_voice(session, skill, voice_id))
    session.commit()
    return Response(status_code=204)


@router.post("/characters/{card_id}/voices/{voice_id}:preview", response_model=VoicePreviewResponse)
def preview_voice(
    card_id: str,
    voice_id: str,
    payload: VoicePreviewRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Write,
) -> VoicePreviewResponse:
    skill, _character = _card(session, user.id, card_id)
    voice = voices_service.find_voice(session, skill, voice_id)
    text = (payload.text or voice.preview_text or voices_service.DEFAULT_PREVIEW_TEXT).strip()
    credits = jobs_service.quote_for(
        session, operation=Operation.AUDIO_GENERATION, quality_tier=payload.quality_tier
    ).credits
    account = credits_service.get_or_create_account(session, user.id)
    available = account.available_balance
    remaining = credits_service.remaining_monthly_spend(account)
    within = remaining is None or remaining >= credits
    response = VoicePreviewResponse(
        credits=credits,
        available_credits=available,
        period_remaining=remaining,
        within_spend_limit=within,
        sufficient=available >= credits and within,
    )
    if payload.dry_run:
        return response
    token = hashlib.sha1(f"{voice.id}:{text}".encode()).hexdigest()[:12]
    key = f"{(idempotency_key or new_id('idk'))[:100]}:{token}"
    replayed = session.scalar(
        select(GenerationJob).where(
            GenerationJob.user_id == user.id, GenerationJob.idempotency_key == key
        )
    )
    if replayed is not None:
        return response.model_copy(update={"job_id": replayed.id, "replayed": True})
    if available < credits:
        raise InsufficientCredits(
            f"需要 {credits} 积分，当前可用 {available}。", required=credits, available=available
        )
    if not within:
        raise SpendLimitExceeded(
            f"需要 {credits} 积分，本月消费上限还剩 {remaining}。",
            required=credits,
            remaining=remaining,
        )
    if payload.text:
        voice.preview_text = text[: voices_service.MAX_PREVIEW_TEXT_LEN]
    rate_limit.enforce("generation_submit", client_identity(request, user))
    params = GenerationParams.model_validate(
        {"prompt": text, "target_voice_id": voice.id, "voice_profile_id": voice.id}
    ).model_dump()
    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=Operation.AUDIO_GENERATION,
        quality_tier=payload.quality_tier,
        params=params,
        idempotency_key=key,
    )
    session.commit()
    if not result.replayed:
        job_dispatch.enqueue_or_fail(session, result.job)
    return response.model_copy(update={"job_id": result.job.id})


@router.post("/characters/{card_id}/voices:match", response_model=VoiceMatchResponse)
def match_voice(
    card_id: str,
    payload: VoiceMatchRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> VoiceMatchResponse:
    _skill, character = _card(session, user.id, card_id)
    description = (payload.voice_description or character.voice_description or "").strip()
    if not description:
        raise ValidationFailed(
            "先写一段音色描述，再让 AI 匹配。", fields={"voice_description": "不能为空"}
        )
    options = [
        character_profile.VoiceOption(model=m, voice=v, params=p, emotions=e)
        for m, v, p, e in voices_service.preset_options(session)
    ]
    match = character_profile.match_voice(
        session,
        name=character.name,
        voice_description=description,
        options=options,
        user_id=user.id,
    )
    session.commit()
    return VoiceMatchResponse(
        model=match.option.model,
        model_label=model_catalog.display_name_for_model(match.option.model) or match.option.model,
        voice=match.option.voice,
        params=VoiceParams(speed=match.speed, emotion=match.emotion),
        reason=match.reason,
    )
