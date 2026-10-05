"""P7: a character's voices — roster and knob validation, clone consent,
the default voice, look binding, derivation edges and job parameters."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.characters import voice_resolver, voices
from app.domain.consent import service as consent_service
from app.domain.errors import AssetRightsRequired, NotFound, ValidationFailed
from app.domain.scenes import service as scenes_service
from app.models import Asset, CreationSkill, User
from app.models.base import new_id
from app.models.enums import MediaType, Operation
from app.providers import model_catalog


def _character(db: Session, owner: User, name: str = "林夏") -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=owner.id,
        name=name,
        description=None,
        reference_asset_ids=[],
        voice_description="清亮的年轻女声",
    ).skill


def _audio(db: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp3",
        media_type=MediaType.AUDIO,
        mime_type="audio/mpeg",
        size_bytes=2048,
        checksum_sha256="a" * 64,
        role="voice_sample",
    )
    db.add(asset)
    db.flush()
    return asset


def _preset(name: str = "日常", **overrides) -> voices.VoiceFields:
    return voices.VoiceFields(
        name=name, source="preset", model="tts-pro", voice="柔美女友", **overrides
    )


def test_the_first_voice_is_the_default_and_deleting_it_promotes_the_next(
    db: Session, author: User
) -> None:
    skill = _character(db, author)
    first = voices.create_voice(db, skill, _preset("日常"))
    second = voices.create_voice(db, skill, _preset("哭腔"))
    assert (first.is_default, second.is_default) == (True, False)
    voices.delete_voice(db, skill, first)
    db.refresh(second)
    assert second.is_default is True
    voices.update_voice(
        db, skill, voices.create_voice(db, skill, _preset("怒吼")), make_default=True
    )
    db.refresh(second)
    assert second.is_default is False


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            voices.VoiceFields(name="x", source="preset", model="tts-pro", voice="不存在"),
            "没有该音色",
        ),
        (voices.VoiceFields(name="x", source="preset", model="tts-pro"), "模型和音色"),
        (
            voices.VoiceFields(
                name="x", source="preset", model="tts-pro", voice="柔美女友", params={"speed": 1.2}
            ),
            "语速",
        ),
        (
            voices.VoiceFields(
                name="x",
                source="preset",
                model="tts-pro",
                voice="柔美女友",
                params={"emotion": "sad"},
            ),
            "情绪",
        ),
        (
            voices.VoiceFields(
                name="x", source="preset", model="tts-1", voice="alloy", params={"speed": 9}
            ),
            "语速需在",
        ),
        (voices.VoiceFields(name="x", source="clone"), "声音样本"),
        (
            voices.VoiceFields(
                name="x", source="preset", model="tts-1", voice="alloy", attributes={"use": "唱歌"}
            ),
            "用途",
        ),
    ],
)
def test_voice_fields_are_validated(
    db: Session, author: User, fields: voices.VoiceFields, message: str
) -> None:
    skill = _character(db, author)
    with pytest.raises(ValidationFailed, match=message):
        voices.create_voice(db, skill, fields)


def test_knobs_follow_the_model(db: Session, author: User) -> None:
    skill = _character(db, author)
    fast = voices.create_voice(
        db,
        skill,
        voices.VoiceFields(
            name="快", source="preset", model="tts-1", voice="nova", params={"speed": 1.25}
        ),
    )
    angry = voices.create_voice(db, skill, _preset("愤怒", params={"emotion": "angry"}))
    assert fast.params_json == {"speed": 1.25}
    assert angry.params_json == {"emotion": "angry"}
    assert model_catalog.voice_capabilities("TTS-PRO")[1] == model_catalog.TTS_PRO_EMOTIONS


def test_names_are_unique_per_card(db: Session, author: User) -> None:
    skill = _character(db, author)
    voices.create_voice(db, skill, _preset("日常"))
    with pytest.raises(ValidationFailed, match="同名"):
        voices.create_voice(db, skill, _preset("日常"))
    # Another card may reuse it.
    voices.create_voice(db, _character(db, author, "周岩"), _preset("日常"))


def test_a_clone_needs_an_owned_audio_sample_with_consent(
    db: Session, author: User, remixer: User
) -> None:
    skill = _character(db, author)
    theirs = _audio(db, remixer)
    with pytest.raises(ValidationFailed, match="不存在"):
        voices.create_voice(
            db, skill, voices.VoiceFields(name="克隆", source="clone", sample_asset_id=theirs.id)
        )
    sample = _audio(db, author)
    with pytest.raises(AssetRightsRequired):
        voices.create_voice(
            db, skill, voices.VoiceFields(name="克隆", source="clone", sample_asset_id=sample.id)
        )
    consent_service.declare(
        db,
        user=author,
        asset_id=sample.id,
        consent_type="voice",
        subject_reference="配音演员甲",
    )
    clone = voices.create_voice(
        db, skill, voices.VoiceFields(name="克隆", source="clone", sample_asset_id=sample.id)
    )
    assert voices.job_params(clone) == {"extra": {}, "reference_asset_ids": [sample.id]}


def test_looks_bind_to_their_own_cards_voices(db: Session, author: User) -> None:
    skill = _character(db, author)
    young = av.create_variant(db, skill, name="少年")
    old = av.create_variant(db, skill, name="老年")
    voice = voices.create_voice(db, skill, _preset("少年音"))
    voices.bind_looks(db, skill, voice, [young.id])
    assert voices.bound_look_ids(skill, voice) == [young.id]
    voices.bind_looks(db, skill, voice, [old.id])
    assert young.voice_id is None and old.voice_id == voice.id
    foreign = av.create_variant(db, _character(db, author, "周岩"), name="战甲")
    with pytest.raises(ValidationFailed):
        voices.bind_looks(db, skill, voice, [foreign.id])
    # Deleting a voice unbinds its looks.
    voices.delete_voice(db, skill, voice)
    assert old.voice_id is None
    # A look of another card cannot take this card's voice.
    other_voice = voices.create_voice(db, skill, _preset("备用"))
    with pytest.raises(NotFound):
        voices.set_look_voice(db, _character(db, author, "郑国峰"), foreign, other_voice.id)


def test_a_scene_cannot_have_voices(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="码头", description=None, reference_asset_ids=[]
    ).skill
    with pytest.raises(ValidationFailed):
        voices.create_voice(db, scene, _preset())


def test_the_voice_for_a_look_falls_back_to_the_default(db: Session, author: User) -> None:
    skill = _character(db, author)
    default = voices.create_voice(db, skill, _preset("日常"))
    old_voice = voices.create_voice(db, skill, _preset("老年"))
    old = av.create_variant(db, skill, name="老年")
    voices.set_look_voice(db, skill, old, old_voice.id)
    assert voices.voice_for_look(db, skill, old.id) is old_voice
    assert voices.voice_for_look(db, skill, av.find_default(skill).id) is default
    assert voices.voice_for_look(db, skill, None) is default


def test_deriving_records_what_changed(db: Session, author: User) -> None:
    skill = _character(db, author)
    base = voices.create_voice(db, skill, _preset("日常", attributes={"age_stage": "youth"}))
    angry, edge = voices.derive_voice(
        db,
        skill,
        base,
        voices.VoiceFields(
            name="暴怒",
            source="",
            params={"emotion": "angry"},
            attributes={"age_stage": "youth", "emotion": "愤怒"},
        ),
    )
    assert (angry.model, angry.voice) == ("tts-pro", "柔美女友")
    assert edge is not None
    assert edge.level == "voice"
    assert edge.relations_json == ["emotion", "params"]
    # Voice edges keep the DAG rule.
    with pytest.raises(ValidationFailed, match="形成环"):
        graph.add_edge(
            db,
            skill,
            level="voice",
            source_id=angry.id,
            target_id=base.id,
            relations=["custom"],
            label="回溯",
        )
    with pytest.raises(ValidationFailed):
        graph.add_edge(
            db, skill, level="voice", source_id=base.id, target_id=angry.id, relations=["outfit"]
        )


def test_the_resolver_turns_a_voice_into_job_params(
    db: Session, author: User, remixer: User
) -> None:
    skill = _character(db, author)
    voice = voices.create_voice(db, skill, _preset("愤怒", params={"emotion": "angry"}))
    params = {
        "prompt": "你给我站住！",
        "voice_profile_id": voice.id,
        "voice_card_id": "sk_forged",
        "forced_model": "tts-1",
        "extra": {"voice": "alloy", "lang": "zh"},
    }
    voice_resolver.apply_voice_profile(
        db, user_id=author.id, operation=Operation.AUDIO_GENERATION, params=params
    )
    assert params["forced_model"] == "tts-pro"
    assert params["extra"] == {"lang": "zh", "voice": "柔美女友", "emotion": "angry"}
    assert params["voice_card_id"] == skill.id
    assert params["reference_asset_ids"] == []

    with pytest.raises(NotFound):
        voice_resolver.apply_voice_profile(
            db,
            user_id=remixer.id,
            operation=Operation.AUDIO_GENERATION,
            params={"prompt": "x", "voice_profile_id": voice.id},
        )
    with pytest.raises(ValidationFailed):
        voice_resolver.apply_voice_profile(
            db,
            user_id=author.id,
            operation=Operation.TEXT_TO_IMAGE,
            params={"prompt": "x", "voice_profile_id": voice.id},
        )
