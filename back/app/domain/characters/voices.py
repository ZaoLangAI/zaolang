"""A character card's voices (P7, `CharacterVoice`).

A voice is either a TTS model's **preset** voice with the parameters that
model takes (`model_catalog.voice_capabilities`: `speed` for tts-1 /
tts-1-hd, `emotion` for tts-pro), or a **clone** of an uploaded sample,
which needs the speaker's active voice consent (深度合成管理规定 §14).

Invariants:

- Owner-only graph metadata, like edges: never published, never shown to
  an unlocker, and writing one does not withdraw a published card.
- Names are unique per card; at most `MAX_VOICES_PER_CHARACTER`; one
  default per card — the first voice becomes it, and deleting the default
  promotes the next (voices are optional, unlike looks).
- A look binds to at most one voice of its own card
  (`SkillAssetVariant.voice_id`); a voice lists the looks bound to it.
- A preset voice must be in its model's roster when the catalogue knows
  one; unknown models keep any voice id (the provider is the judge, same as
  `audio_generation` itself).
- `job_params` is the single place a voice turns into job parameters —
  `voice_resolver.apply_voice_profile` and the preview endpoint use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph_service
from app.domain.asset_variants import service as av
from app.domain.consent import service as consent_service
from app.domain.errors import AssetRightsRequired, NotFound, ValidationFailed
from app.domain.image_assets.vocabulary import AGE_STAGE_PRESETS
from app.models import Asset, CharacterVoice, CreationSkill, SkillAssetVariant
from app.models.enums import (
    AssetGraphLevel,
    AssetRelation,
    ConsentType,
    MediaType,
    Operation,
    VoiceSource,
)
from app.providers import model_catalog

MAX_VOICES_PER_CHARACTER = 48
MAX_VOICE_NAME_LEN = 40
MAX_PREVIEW_TEXT_LEN = 200
MAX_VOICE_EMOTION_LEN = 20
VOICE_USES = ("dialogue", "inner_monologue", "narration")
MAX_CUSTOM_ATTRIBUTES = av.MAX_CUSTOM_ATTRIBUTES
DEFAULT_PREVIEW_TEXT = "你好，很高兴认识你。今天的天气真不错，我们一起出去走走吧。"


# ---- reads -----------------------------------------------------------------------


def voices(session: Session, skill: CreationSkill) -> list[CharacterVoice]:
    """Default first, then `sort_order`, then age."""
    return list(
        session.scalars(
            select(CharacterVoice)
            .where(CharacterVoice.skill_id == skill.id)
            .order_by(
                CharacterVoice.is_default.desc(),
                CharacterVoice.sort_order,
                CharacterVoice.created_at,
            )
        )
    )


def find_voice(session: Session, skill: CreationSkill, voice_id: str) -> CharacterVoice:
    voice = session.get(CharacterVoice, voice_id)
    if voice is None or voice.skill_id != skill.id:
        raise NotFound("音色不存在。")
    return voice


def default_voice(session: Session, skill: CreationSkill) -> CharacterVoice | None:
    return session.scalar(
        select(CharacterVoice).where(CharacterVoice.skill_id == skill.id, CharacterVoice.is_default)
    )


def bound_look_ids(skill: CreationSkill, voice: CharacterVoice) -> list[str]:
    return [variant.id for variant in skill.asset_variants if variant.voice_id == voice.id]


def voice_for_look(
    session: Session, skill: CreationSkill, look_id: str | None
) -> CharacterVoice | None:
    """The voice a look speaks with: its bound voice, else the card's default."""
    look = av.find_variant(skill, look_id) if look_id else None
    if look is not None and look.voice_id:
        bound = session.get(CharacterVoice, look.voice_id)
        if bound is not None and bound.skill_id == skill.id:
            return bound
    return default_voice(session, skill)


# ---- validation ------------------------------------------------------------------


def _check_name(
    session: Session, skill: CreationSkill, name: str, exclude_id: str | None = None
) -> str:
    clean = name.strip()[:MAX_VOICE_NAME_LEN]
    if not clean:
        raise ValidationFailed("音色名称不能为空。", fields={"name": "不能为空"})
    clash = session.scalar(
        select(CharacterVoice.id).where(
            CharacterVoice.skill_id == skill.id,
            CharacterVoice.name == clean,
            CharacterVoice.id != (exclude_id or ""),
        )
    )
    if clash is not None:
        raise ValidationFailed("已有同名的音色。", fields={"name": "名称已存在"})
    return clean


def check_params(model: str | None, params: dict[str, Any] | None) -> dict[str, Any]:
    """Keeps only the knobs `model` takes, validated."""
    raw = dict(params or {})
    allowed, emotions = model_catalog.voice_capabilities(model or "")
    clean: dict[str, Any] = {}
    speed = raw.get("speed")
    if speed is not None:
        if "speed" not in allowed:
            raise ValidationFailed("这个模型不支持调节语速。", fields={"params.speed": "不支持"})
        low, high = model_catalog.VOICE_SPEED_RANGE
        try:
            value = round(float(speed), 2)
        except (TypeError, ValueError):
            raise ValidationFailed("语速必须是数字。", fields={"params.speed": "无效"}) from None
        if not low <= value <= high:
            raise ValidationFailed(
                f"语速需在 {low}–{high} 之间。", fields={"params.speed": "超出范围"}
            )
        clean["speed"] = value
    emotion = raw.get("emotion")
    if emotion:
        if "emotion" not in allowed:
            raise ValidationFailed("这个模型不支持情绪参数。", fields={"params.emotion": "不支持"})
        if emotions and emotion not in emotions:
            raise ValidationFailed("不支持的情绪。", fields={"params.emotion": "无效"})
        clean["emotion"] = str(emotion)
    return clean


def check_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(attributes or {})
    foreign = sorted(set(raw) - {"age_stage", "emotion", "use", "custom"})
    if foreign:
        raise ValidationFailed(
            f"不支持这些属性：{'、'.join(foreign)}。", fields={"attributes": "无效"}
        )
    clean: dict[str, Any] = {}
    age = raw.get("age_stage")
    if age:
        if age not in AGE_STAGE_PRESETS:
            raise ValidationFailed("年龄阶段无效。", fields={"attributes.age_stage": "无效"})
        clean["age_stage"] = age
    emotion = str(raw.get("emotion") or "").strip()
    if emotion:
        if len(emotion) > MAX_VOICE_EMOTION_LEN:
            raise ValidationFailed("情绪描述过长。", fields={"attributes.emotion": "过长"})
        clean["emotion"] = emotion
    use = raw.get("use")
    if use:
        if use not in VOICE_USES:
            raise ValidationFailed("用途无效。", fields={"attributes.use": "无效"})
        clean["use"] = use
    # Same rules as a look's custom key-values.
    custom = av.check_custom_attributes(raw.get("custom"))
    if custom:
        clean["custom"] = custom
    return clean


def _check_preset(model: str | None, voice: str | None) -> tuple[str, str]:
    model_clean = (model or "").strip()
    voice_clean = (voice or "").strip()
    if not model_clean or not voice_clean:
        raise ValidationFailed("预设音色需要选择模型和音色。", fields={"voice": "不能为空"})
    roster = model_catalog.voices_for_model(model_clean)
    if roster and voice_clean not in roster:
        raise ValidationFailed("这个模型没有该音色。", fields={"voice": "不在音色列表中"})
    return model_clean[:200], voice_clean[:60]


def _check_sample(session: Session, skill: CreationSkill, asset_id: str | None) -> str:
    if not asset_id:
        raise ValidationFailed("克隆音色需要上传声音样本。", fields={"sample_asset_id": "不能为空"})
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != skill.owner_user_id:
        raise ValidationFailed("声音样本不存在。", fields={"sample_asset_id": "不存在"})
    if asset.media_type != MediaType.AUDIO:
        raise ValidationFailed("声音样本必须是音频。", fields={"sample_asset_id": "不是音频"})
    if (
        consent_service.active_consent(
            session, asset_id=asset.id, consent_type=ConsentType.VOICE.value
        )
        is None
    ):
        raise AssetRightsRequired(
            "使用声音克隆前，请先提交被克隆人的授权声明。",
            asset_id=asset.id,
            consent_type=ConsentType.VOICE.value,
        )
    return asset.id


# ---- writes ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceFields:
    name: str
    source: str
    description: str | None = None
    model: str | None = None
    voice: str | None = None
    params: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    sample_asset_id: str | None = None
    preview_text: str | None = None


def create_voice(session: Session, skill: CreationSkill, fields: VoiceFields) -> CharacterVoice:
    if not av.is_character(skill):
        raise ValidationFailed("只有角色可以设置音色。", fields={"card": "不是角色"})
    count = session.scalar(
        select(func.count()).select_from(CharacterVoice).where(CharacterVoice.skill_id == skill.id)
    )
    if (count or 0) >= MAX_VOICES_PER_CHARACTER:
        raise ValidationFailed(
            f"每个角色最多 {MAX_VOICES_PER_CHARACTER} 个音色。", fields={"name": "数量已达上限"}
        )
    voice = CharacterVoice(
        skill_id=skill.id,
        name=_check_name(session, skill, fields.name),
        description=(fields.description or "").strip() or None,
        source=fields.source,
        attributes_json=check_attributes(fields.attributes),
        preview_text=(fields.preview_text or "").strip()[:MAX_PREVIEW_TEXT_LEN] or None,
        is_default=not count,
        sort_order=(count or 0),
    )
    _apply_source(session, skill, voice, fields)
    session.add(voice)
    session.flush()
    return voice


def _apply_source(
    session: Session, skill: CreationSkill, voice: CharacterVoice, fields: VoiceFields
) -> None:
    if fields.source == VoiceSource.PRESET:
        voice.model, voice.voice = _check_preset(fields.model, fields.voice)
        voice.params_json = check_params(voice.model, fields.params)
        voice.sample_asset_id = None
    elif fields.source == VoiceSource.CLONE:
        voice.sample_asset_id = _check_sample(session, skill, fields.sample_asset_id)
        voice.model = (fields.model or "").strip()[:200] or None
        voice.voice = None
        voice.params_json = check_params(voice.model, fields.params) if voice.model else {}
    else:
        raise ValidationFailed("音色来源无效。", fields={"source": "无效"})


def update_voice(
    session: Session,
    skill: CreationSkill,
    voice: CharacterVoice,
    *,
    name: str | None = None,
    description: str | None = None,
    source: str | None = None,
    model: str | None = None,
    voice_id: str | None = None,
    params: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    sample_asset_id: str | None = None,
    preview_text: str | None = None,
    make_default: bool = False,
) -> CharacterVoice:
    """Partial update. Changing the source, model, voice, params or sample
    re-validates them together and drops a now-stale preview."""
    if name is not None:
        voice.name = _check_name(session, skill, name, exclude_id=voice.id)
    if description is not None:
        voice.description = description.strip() or None
    if attributes is not None:
        voice.attributes_json = check_attributes(attributes)
    if preview_text is not None:
        voice.preview_text = preview_text.strip()[:MAX_PREVIEW_TEXT_LEN] or None
    if any(v is not None for v in (source, model, voice_id, params, sample_asset_id)):
        fields = VoiceFields(
            name=voice.name,
            source=source or voice.source,
            model=model if model is not None else voice.model,
            voice=voice_id if voice_id is not None else voice.voice,
            params=params if params is not None else voice.params_json,
            sample_asset_id=sample_asset_id
            if sample_asset_id is not None
            else voice.sample_asset_id,
        )
        before = (voice.source, voice.model, voice.voice, voice.params_json, voice.sample_asset_id)
        voice.source = fields.source
        _apply_source(session, skill, voice, fields)
        after = (voice.source, voice.model, voice.voice, voice.params_json, voice.sample_asset_id)
        if before != after:
            voice.preview_asset_id = None
            voice.preview_job_id = None
    if make_default and not voice.is_default:
        current = default_voice(session, skill)
        if current is not None:
            current.is_default = False
            session.flush()
        voice.is_default = True
    session.flush()
    return voice


def delete_voice(session: Session, skill: CreationSkill, voice: CharacterVoice) -> None:
    was_default = voice.is_default
    for variant in skill.asset_variants:
        if variant.voice_id == voice.id:
            variant.voice_id = None
    session.delete(voice)
    session.flush()
    if was_default:
        successor = session.scalar(
            select(CharacterVoice)
            .where(CharacterVoice.skill_id == skill.id)
            .order_by(CharacterVoice.sort_order, CharacterVoice.created_at)
            .limit(1)
        )
        if successor is not None:
            successor.is_default = True
            session.flush()


def bind_looks(
    session: Session, skill: CreationSkill, voice: CharacterVoice, look_ids: list[str]
) -> None:
    """Exactly `look_ids` speak with `voice` afterwards (others it had are
    unbound). Each id must be a look of this card."""
    wanted: list[SkillAssetVariant] = []
    for look_id in dict.fromkeys(look_ids):
        look = av.find_variant(skill, look_id)
        if look is None:
            raise ValidationFailed("造型不存在。", fields={"look_ids": "造型不存在"})
        wanted.append(look)
    for variant in skill.asset_variants:
        if variant.voice_id == voice.id and variant not in wanted:
            variant.voice_id = None
    for look in wanted:
        look.voice_id = voice.id
    session.flush()


def set_look_voice(
    session: Session, skill: CreationSkill, look: SkillAssetVariant, voice_id: str | None
) -> None:
    """A look's own voice binding (the look inspector's picker)."""
    if not av.is_character(skill):
        raise ValidationFailed("只有角色造型可以绑定音色。", fields={"voice_id": "不支持"})
    look.voice_id = find_voice(session, skill, voice_id).id if voice_id else None
    session.flush()


def relations_between(source: CharacterVoice, target: CharacterVoice) -> list[str]:
    """What differs between two voices, as relation types (a derive's auto
    edge)."""
    sa, ta = source.attributes_json or {}, target.attributes_json or {}
    found: list[str] = []
    if sa.get("age_stage") != ta.get("age_stage"):
        found.append(AssetRelation.AGE)
    if sa.get("emotion") != ta.get("emotion"):
        found.append(AssetRelation.EMOTION)
    if sa.get("use") != ta.get("use"):
        found.append(AssetRelation.SCENE)
    if (source.source, source.model, source.voice, source.params_json) != (
        target.source,
        target.model,
        target.voice,
        target.params_json,
    ):
        found.append(AssetRelation.PARAMS)
    if (sa.get("custom") or []) != (ta.get("custom") or []):
        found.append(AssetRelation.CUSTOM)
    return [str(r) for r in found]


def derive_voice(
    session: Session, skill: CreationSkill, source: CharacterVoice, fields: VoiceFields
) -> tuple[CharacterVoice, Any]:
    """A new voice from `source` (unspecified fields inherited) plus the
    voice-level auto edge naming what changed."""
    merged = VoiceFields(
        name=fields.name,
        source=fields.source or source.source,
        description=fields.description if fields.description is not None else source.description,
        model=fields.model if fields.model is not None else source.model,
        voice=fields.voice if fields.voice is not None else source.voice,
        params=fields.params if fields.params is not None else dict(source.params_json or {}),
        attributes=fields.attributes
        if fields.attributes is not None
        else dict(source.attributes_json or {}),
        sample_asset_id=fields.sample_asset_id
        if fields.sample_asset_id is not None
        else source.sample_asset_id,
        preview_text=fields.preview_text
        if fields.preview_text is not None
        else source.preview_text,
    )
    voice = create_voice(session, skill, merged)
    edge = graph_service.add_auto_edge(
        session,
        skill,
        level=AssetGraphLevel.VOICE,
        source_id=source.id,
        target_id=voice.id,
        relations=relations_between(source, voice),
    )
    return voice, edge


def job_params(voice: CharacterVoice) -> dict[str, Any]:
    """What an `audio_generation` job takes from `voice`: the pinned model
    (`forced_model`), `extra.voice` and its knobs — or the clone sample as
    the one reference."""
    extra: dict[str, Any] = {}
    params: dict[str, Any] = {"extra": extra}
    if voice.model:
        params["forced_model"] = voice.model
    if voice.source == VoiceSource.PRESET and voice.voice:
        extra["voice"] = voice.voice
    for key in ("speed", "emotion"):
        value = (voice.params_json or {}).get(key)
        if value is not None:
            extra[key] = value
    if voice.source == VoiceSource.CLONE:
        if not voice.sample_asset_id:
            raise ValidationFailed(
                "这个克隆音色的声音样本已被删除，请重新上传。",
                fields={"voice_profile_id": "缺少样本"},
            )
        params["reference_asset_ids"] = [voice.sample_asset_id]
    return params


def preset_options(session: Session) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    """Every `(model, voice, params, emotions)` a preset voice can use right
    now: audio models enabled in the live routing catalogue that have a
    known roster — what 「AI 按描述匹配」 chooses from."""
    from app.agents import router as routing

    models: list[str] = []
    for capability in routing.build_catalog(session).values():
        model = capability.model_or_workflow
        if Operation.AUDIO_GENERATION.value in capability.operations and model not in models:
            models.append(model)
    options: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
    for model in sorted(models):
        roster = model_catalog.voices_for_model(model)
        if not roster:
            continue
        params, emotions = model_catalog.voice_capabilities(model)
        options.extend((model, name, params, emotions) for name in roster)
    return options
