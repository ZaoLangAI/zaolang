"""Character voices and dialogue delivery: the script's closed `emotion`, a
character's preset voice, and how each TTS upstream receives direction
(`app.providers.tts_direction`)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.domain.characters import service as characters_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import MediaType, Operation
from app.providers import tts_direction
from app.providers.aihubmix_media import AiHubMixMediaProvider
from app.providers.base import GenerationRequest
from app.providers.dmxapi_media import (
    AUDIO_MODEL_GPT4O_MINI_TTS,
    AUDIO_MODEL_TTS_PRO,
    DmxApiMediaProvider,
)


class _FakeResponse:
    content = b"mp3-bytes"

    def raise_for_status(self) -> None:
        return None


def _request(emotion: str | None) -> GenerationRequest:
    extra: dict[str, Any] = {"voice": "nova"}
    if emotion:
        extra["emotion"] = emotion
    return GenerationRequest(
        job_id="job-audio",
        operation=Operation.AUDIO_GENERATION.value,
        quality_tier="standard",
        prompt="你还在等我？",
        aspect_ratio="16:9",
        duration_seconds=0,
        extra=extra,
    )


def _capture_body(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sent: dict[str, Any] = {}

    def fake_post(self: httpx.Client, url: str, **kwargs: Any) -> _FakeResponse:
        sent.update(kwargs["json"])
        return _FakeResponse()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return sent


def _dmx(model: str) -> DmxApiMediaProvider:
    return DmxApiMediaProvider(
        endpoint_id="ep-dmx",
        capability_tag=Operation.AUDIO_GENERATION.value,
        model=model,
        base_url="https://www.dmxapi.cn",
        api_key="test-key",
        timeout_ms=5_000,
    )


def _aihubmix(model: str) -> AiHubMixMediaProvider:
    return AiHubMixMediaProvider(
        endpoint_id="ep-test",
        capability_tag=Operation.AUDIO_GENERATION.value,
        model=model,
        base_url="https://aihubmix.invalid",
        api_key="test-key",
        timeout_ms=5_000,
        protocol="minimax",
    )


# ---- script shape ----------------------------------------------------------


def _script(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": "雨夜",
        "logline": "",
        "characters": [],
        "scenes": [{"heading": "日·客厅", "blocks": blocks}],
    }


def test_the_sanitizer_keeps_a_known_emotion_only_on_dialogue() -> None:
    sanitized = copywriter._sanitize_script(
        _script(
            [
                {"type": "dialogue", "character": "林夏", "text": "你还在等我？", "emotion": "sad"},
                {"type": "dialogue", "character": "周屿", "text": "一直在。", "emotion": "smug"},
                {"type": "action", "character": None, "text": "她转身", "emotion": "angry"},
            ]
        )
    )
    assert sanitized is not None
    blocks = sanitized["scenes"][0]["blocks"]
    assert blocks[0]["emotion"] == "sad"
    # Unknown values and non-dialogue blocks keep the plain 3-key shape.
    assert set(blocks[1]) == {"type", "character", "text"}
    assert set(blocks[2]) == {"type", "character", "text"}


def test_the_prompt_offers_exactly_the_closed_emotion_set() -> None:
    assert '"emotion"' in copywriter.SCRIPT_JSON_SHAPE
    for emotion in copywriter.SCRIPT_EMOTIONS:
        assert emotion in copywriter.SCRIPT_JSON_SHAPE
        assert emotion in copywriter._BLOCK_TYPE_RULES


# ---- provider mapping ------------------------------------------------------


def test_direction_maps_onto_what_each_upstream_accepts() -> None:
    assert tts_direction.tts_pro_emotion("happy") == "happy"
    assert tts_direction.tts_pro_emotion("sad") is None
    assert tts_direction.instructions_for("tts-1", "happy") is None
    assert "calm" in (tts_direction.instructions_for("gpt-4o-mini-tts", "calm") or "")
    assert tts_direction.instructions_for("gpt-4o-mini-tts", "smug") is None


def test_dmxapi_gpt4o_mini_tts_gets_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _capture_body(monkeypatch)
    _dmx(AUDIO_MODEL_GPT4O_MINI_TTS).submit(_request("sad"))
    assert "sad" in body["instructions"]
    assert "emotion" not in body


def test_dmxapi_tts_pro_drops_an_emotion_outside_its_own_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _capture_body(monkeypatch)
    _dmx(AUDIO_MODEL_TTS_PRO).submit(_request("sad"))
    assert "emotion" not in body
    assert "instructions" not in body


def test_aihubmix_forwards_instructions_only_to_gpt4o_mini_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _capture_body(monkeypatch)
    _aihubmix("gpt-4o-mini-tts").submit(_request("happy"))
    assert "happy" in body["instructions"]
    body.clear()
    _aihubmix("tts-1").submit(_request("happy"))
    assert "instructions" not in body


def test_no_emotion_leaves_the_request_body_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _capture_body(monkeypatch)
    _aihubmix("gpt-4o-mini-tts").submit(_request(None))
    assert set(body) == {"model", "input", "voice", "response_format"}


# ---- character preset voice ------------------------------------------------


def _image(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def test_a_preset_voice_round_trips_and_clears(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
        preset_voice="nova",
    )
    assert character.preset_voice == "nova"
    kept = characters_service.update_character(
        db, user_id=author.id, character_id=character.id, description="新设定"
    )
    assert kept.preset_voice == "nova"
    cleared = characters_service.update_character(
        db, user_id=author.id, character_id=character.id, preset_voice=""
    )
    assert cleared.preset_voice is None


def test_an_audio_job_takes_the_characters_voice_but_never_its_images(
    db: Session, author: User
) -> None:
    image = _image(db, author)
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[image.id],
        voice_description=None,
        preset_voice="nova",
    )

    audio: dict[str, Any] = {"character_ids": [character.id], "extra": {}}
    characters_service.apply_character_refs(
        db, user_id=author.id, params=audio, operation=Operation.AUDIO_GENERATION
    )
    assert not audio.get("reference_asset_ids")
    assert audio["extra"]["voice"] == "nova"

    chosen: dict[str, Any] = {"character_ids": [character.id], "extra": {"voice": "alloy"}}
    characters_service.apply_character_refs(
        db, user_id=author.id, params=chosen, operation=Operation.AUDIO_GENERATION
    )
    assert chosen["extra"]["voice"] == "alloy"

    picture: dict[str, Any] = {"character_ids": [character.id]}
    characters_service.apply_character_refs(
        db, user_id=author.id, params=picture, operation=Operation.TEXT_TO_IMAGE
    )
    assert picture["reference_asset_ids"] == [image.id]
    assert "voice" not in picture["extra"]
