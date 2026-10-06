"""Turns `voice_profile_id` / `target_voice_id` on an `audio_generation`
job into what providers read (P7), at submit — before references are
ownership- and consent-checked and before quoting, so a stale or foreign
voice never reserves credits.

The voice's model becomes `forced_model`; its preset voice and knobs
replace `extra.voice/emotion/speed`; a clone's sample becomes the one
reference (consent is then checked by `assert_reference_consents` like any
clone). `voice_card_id` records the voice's card for the graph's pending
jobs. Voices unlock with their card: a buyer of a published character
(`skill_library.card_is_usable_by`) may name its voices, a clone's sample
included; previews (`target_voice_id`) write onto the voice, so they stay
the owner's. Any other voice is a 404, like the rest of the library.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.characters import voices as voices_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.skill_library import service as skill_library_service
from app.models import CharacterVoice, CreationSkill
from app.models.enums import Operation

_VOICE_KNOBS = ("voice", "emotion", "speed")


def apply_voice_profile(
    session: Session, *, user_id: str, operation: str, params: dict[str, Any]
) -> None:
    params.pop("voice_card_id", None)
    profile_id = params.get("voice_profile_id")
    target_id = params.get("target_voice_id")
    if not profile_id and not target_id:
        return
    if operation != Operation.AUDIO_GENERATION:
        raise ValidationFailed(
            "角色音色只适用于音频生成。", fields={"params.voice_profile_id": "不适用"}
        )
    if profile_id and target_id and profile_id != target_id:
        raise ValidationFailed(
            "试听任务只能使用它自己的音色。", fields={"params.target_voice_id": "不一致"}
        )
    voice = session.get(CharacterVoice, str(profile_id or target_id))
    skill = session.get(CreationSkill, voice.skill_id) if voice is not None else None
    if voice is None or skill is None:
        raise NotFound("音色不存在。")
    owner = skill.owner_user_id == user_id
    if not owner and (
        target_id or not skill_library_service.card_is_usable_by(session, skill, user_id)
    ):
        raise NotFound("音色不存在。")
    resolved = voices_service.job_params(voice)
    params["voice_profile_id"] = voice.id
    params["voice_card_id"] = skill.id
    if resolved.get("forced_model"):
        params["forced_model"] = resolved["forced_model"]
    extra = {k: v for k, v in dict(params.get("extra") or {}).items() if k not in _VOICE_KNOBS}
    extra.update(resolved["extra"])
    params["extra"] = extra
    params["reference_asset_ids"] = list(resolved.get("reference_asset_ids") or [])
