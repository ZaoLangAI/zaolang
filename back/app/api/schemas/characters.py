"""Character library payloads.

A character is stored as a `CreationSkill` (`category=character`) — see
`app.domain.characters.service.CharacterView` — so `CharacterResponse` also
surfaces the skill lifecycle fields (`status`/`visibility`/`access_credits`)
a character library UI needs to show "draft / 审核中 / 已发布".
"""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.common import ApiModel, Timestamped
from app.models.enums import CharacterViewAngle, CreationSkillStatus, CreationSkillVisibility


class CharacterCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=4)
    voice_description: str | None = Field(default=None, max_length=500)
    # The TTS voice id this character is dubbed with by default (a name from
    # an audio model's `voices` roster) — `AUDIO_VOICE_MAX_LENGTH`.
    preset_voice: str | None = Field(default=None, max_length=60)


class CharacterUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] | None = Field(default=None, max_length=4)
    voice_description: str | None = Field(default=None, max_length=500)
    # `None` leaves it unchanged; `""` clears it.
    preset_voice: str | None = Field(default=None, max_length=60)


class CharacterReferenceAssetUpdateRequest(ApiModel):
    view: CharacterViewAngle | None = None
    label: str | None = Field(default=None, max_length=60)


class CharacterPublishRequest(ApiModel):
    # Explicit, per-publish opt-in — see `characters.service.publish_character`.
    portrait_consent: bool = False


class CharacterReferenceAsset(ApiModel):
    asset_id: str
    view: str = CharacterViewAngle.GENERAL.value
    label: str | None = None
    url: str | None = None
    created_at: dt.datetime | None = None


class CharacterActionClip(ApiModel):
    """A generated `video_asset_kind=character_action` clip — see
    `characters.service.CHARACTER_ACTION_CLIPS_KEY`. No `view` field (unlike
    `CharacterReferenceAsset`): a video clip has no fixed pose/angle."""

    asset_id: str
    label: str | None = None
    url: str | None = None
    created_at: dt.datetime | None = None


class CharacterResponse(Timestamped):
    id: str
    name: str
    description: str | None = None
    reference_assets: list[CharacterReferenceAsset] = Field(default_factory=list)
    # Generated video clips (`video_asset_kind=character_action`) — separate
    # from `reference_assets` above, never folded into it: see
    # `characters.service.CHARACTER_ACTION_CLIPS_KEY`'s docstring for why a
    # video clip must not be mixed into the still-reference list that feeds
    # a future *image* generation's `reference_asset_ids`.
    action_clips: list[CharacterActionClip] = Field(default_factory=list)
    voice_description: str | None = None
    preset_voice: str | None = None
    status: CreationSkillStatus = CreationSkillStatus.DRAFT
    visibility: CreationSkillVisibility = CreationSkillVisibility.PRIVATE
    access_credits: int = 0
