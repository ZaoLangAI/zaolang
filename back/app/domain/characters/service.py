"""Character library and the series that cast them.

A character is a reusable cast member: a name, up to a few reference images
and a text voice description — stored as a `CreationSkill` with
`category=CHARACTER` rather than a bespoke table (see `CharacterView` below
for why callers never need to know that). A series is a named cast roster
plus the episode numbering that published `Work` rows carry, so a creator
can ask for "the same face and voice" on episode two without retyping
anything.

Nothing here talks to a TTS or face-consistency provider directly.
`voice_description` and reference images are carried through to the job so
the media endpoint selected from Models has something to match against.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, Series, Work
from app.models.base import utcnow
from app.models.enums import (
    CharacterViewAngle,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    MediaType,
    SeriesKind,
)
from app.presenters import media_urls

MAX_REFERENCE_ASSETS = 4
# Mirrors GenerationParams.reference_asset_ids / character_ids in jobs.py —
# kept here too so a validation error names the right limit before a job ever
# reaches the API schema.
MAX_JOB_REFERENCE_ASSETS = 9
MAX_SELECTED_CHARACTERS = 4

# Sub-key inside `CreationSkill.params_json` a character skill's structured
# data lives under, kept apart from the generic `prompt`/`prompt_suffix`/
# `aspect_ratio` keys other skill categories use (see
# `app.workflows.nodes.execute_skill_context`).
CHARACTER_PARAMS_KEY = "character"

_REFERENCE_MEDIA_TYPES = (MediaType.IMAGE, MediaType.VIDEO)


@dataclass(slots=True)
class CharacterView:
    """A character-shaped projection of the underlying `CreationSkill` row.

    Every caller (`api/v1/characters.py`, `apply_character_refs`,
    notifications) keeps talking about "characters" — name, description,
    voice, reference assets — instead of learning the generic skill schema.
    """

    skill: CreationSkill

    @property
    def id(self) -> str:
        return self.skill.id

    @property
    def name(self) -> str:
        return self.skill.title

    @property
    def description(self) -> str | None:
        return _payload(self.skill).get("description") or None

    @property
    def voice_description(self) -> str | None:
        return _payload(self.skill).get("voice_description") or None

    @property
    def reference_assets(self) -> list[dict[str, Any]]:
        return list(_reference_assets(self.skill))

    @property
    def reference_asset_ids(self) -> list[str]:
        return [str(entry["asset_id"]) for entry in self.reference_assets if entry.get("asset_id")]

    @property
    def status(self) -> str:
        return self.skill.status

    @property
    def visibility(self) -> str:
        return self.skill.visibility

    @property
    def access_credits(self) -> int:
        return self.skill.access_credits

    @property
    def portrait_consent_at(self) -> str | None:
        """When the owner last agreed to publish this likeness, if ever.

        Set only by `publish_character` — used by the moderation reviewer to
        confirm consent was captured before a character skill ever reaches
        `PENDING_REVIEW`, since `params_json` is otherwise opaque to review."""
        raw = _payload(self.skill).get("portrait_consent_at")
        return str(raw) if raw else None

    @property
    def created_at(self) -> dt.datetime:
        return self.skill.created_at

    @property
    def updated_at(self) -> dt.datetime:
        return self.skill.updated_at


def _payload(skill: CreationSkill) -> dict[str, Any]:
    """A shallow *copy* of the character's nested payload — never the live
    dict stored inside `skill.params_json`.

    Every caller goes on to mutate the returned dict (and the `list[dict]`
    under its `reference_assets` key) before handing it to `_set_payload`.
    Handing out the live reference instead would mutate the JSON column's
    *current* value in place before the reassignment SQLAlchemy relies on to
    detect a change — the before/after comparison at flush time would then
    see two dicts that are `==` (they share the same mutated nested object),
    conclude nothing changed, and silently skip the `UPDATE`. The write would
    appear to work for the rest of the request (the in-memory object is
    correct) but vanish the moment this `CreationSkill` is re-fetched from a
    fresh row — e.g. a different request, or this one after the identity map
    drops it. `_reference_assets` inherits the same requirement, since its
    entries are the dicts a caller then edits via `update_reference_asset`.
    """
    raw = skill.params_json.get(CHARACTER_PARAMS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _reference_assets(skill: CreationSkill) -> list[dict[str, Any]]:
    """Copies of each reference-asset entry, for the same reason `_payload`
    copies its dict: `update_reference_asset` mutates the entries this
    returns (`entry["view"] = ...`) in place. A plain `[e for e in raw ...]`
    filter makes a new *list* but keeps the same entry *dict* objects, which
    would still be shared with (and therefore corrupt) whatever `params_json`
    was loaded with."""
    raw = _payload(skill).get("reference_assets")
    return (
        [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
    )


def _set_payload(skill: CreationSkill, payload: dict[str, Any]) -> None:
    skill.params_json = {**skill.params_json, CHARACTER_PARAMS_KEY: payload}


def _short_description(description: str | None) -> str:
    """`CreationSkill.description` is a bounded `VARCHAR(300)` used for the
    skill library's own search/listing; a character's full text lives in
    `params_json` instead, so nothing here truncates the author's own copy."""
    return (description or "").strip()[:300]


def _owned_character_skill(session: Session, *, user_id: str, character_id: str) -> CreationSkill:
    skill = session.get(CreationSkill, character_id)
    # Same 404 for missing, someone else's, or a non-character skill —
    # existence (and category) is not confirmed.
    if (
        skill is None
        or skill.owner_user_id != user_id
        or skill.category != CreationSkillCategory.CHARACTER
    ):
        raise NotFound("角色不存在。")
    return skill


def _owned_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = session.get(Series, series_id)
    # Drama rows share this table (`kind=drama`) but are not a cast roster.
    # Same 404 as missing: `/v1/series` must not confirm a production project.
    if series is None or series.owner_user_id != user_id or series.kind != SeriesKind.CAST:
        raise NotFound("系列不存在。")
    return series


def _validate_reference_assets(
    session: Session, *, user_id: str, asset_ids: list[str]
) -> list[str]:
    """Images or videos: a locked-in character look is as often a generated
    clip (kept for face/motion consistency) as it is a still — see
    `zaolang-media-assets`'s "a normal reference accepts up to 9 images/videos"."""
    deduped = list(dict.fromkeys(asset_ids))
    if len(deduped) > MAX_REFERENCE_ASSETS:
        raise ValidationFailed(
            f"参考素材最多 {MAX_REFERENCE_ASSETS} 个。",
            fields={"reference_asset_ids": f"不能超过 {MAX_REFERENCE_ASSETS} 个"},
        )
    for asset_id in deduped:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_user_id != user_id:
            raise NotFound("参考素材不存在。")
        if asset.media_type not in _REFERENCE_MEDIA_TYPES:
            raise ValidationFailed(
                "角色参考素材必须是图片或视频。", fields={"reference_asset_ids": "必须是图片或视频"}
            )
    return deduped


def _entries_from_flat_ids(asset_ids: list[str]) -> list[dict[str, Any]]:
    now = utcnow().isoformat()
    return [
        {
            "asset_id": asset_id,
            "view": CharacterViewAngle.GENERAL.value,
            "label": None,
            "created_at": now,
        }
        for asset_id in asset_ids
    ]


# ---- Character CRUD (adapter over the skill library) --------------------


def create_character(
    session: Session,
    *,
    user_id: str,
    name: str,
    description: str | None,
    reference_asset_ids: list[str],
    voice_description: str | None,
) -> CharacterView:
    refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
    clean_description = (description or "").strip() or None
    skill = skill_library_service.create(
        session,
        owner_user_id=user_id,
        title=name.strip(),
        description=_short_description(clean_description),
        category=CreationSkillCategory.CHARACTER,
        params_json={
            CHARACTER_PARAMS_KEY: {
                "description": clean_description,
                "voice_description": (voice_description or "").strip() or None,
                "reference_assets": _entries_from_flat_ids(refs),
            }
        },
        cover_asset_id=None,
    )
    return CharacterView(skill)


def list_characters(session: Session, *, user_id: str) -> list[CharacterView]:
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == user_id,
            CreationSkill.category == CreationSkillCategory.CHARACTER,
        )
        .order_by(CreationSkill.created_at.desc())
    )
    return [CharacterView(skill) for skill in session.scalars(stmt)]


def get_character(session: Session, *, user_id: str, character_id: str) -> CharacterView:
    return CharacterView(
        _owned_character_skill(session, user_id=user_id, character_id=character_id)
    )


def update_character(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    name: str | None = None,
    description: str | None = None,
    reference_asset_ids: list[str] | None = None,
    voice_description: str | None = None,
) -> CharacterView:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    payload = _payload(skill)
    if name is not None:
        skill.title = name.strip()
    if description is not None:
        clean = description.strip() or None
        payload["description"] = clean
        skill.description = _short_description(clean)
    if voice_description is not None:
        payload["voice_description"] = voice_description.strip() or None
    if reference_asset_ids is not None:
        refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
        payload["reference_assets"] = _entries_from_flat_ids(refs)
    _set_payload(skill, payload)
    # Editing a shared skill's content withdraws it from the marketplace
    # until the owner re-publishes — same rule as any other `CreationSkill`
    # (`skill_library.service.update`); a character swapped mid-share must
    # not keep showing a buyer stale claims about what they are getting.
    if skill.status != CreationSkillStatus.DRAFT:
        skill.status = CreationSkillStatus.DRAFT
        skill.visibility = CreationSkillVisibility.PRIVATE
        skill.reject_reason = None
    session.flush()
    return CharacterView(skill)


def delete_character(session: Session, *, user_id: str, character_id: str) -> None:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    # Leaving a stale id in a series' roster would surface as a silent no-op
    # the next time the cast is resolved, so the roster is cleaned up here.
    for series in session.scalars(
        select(Series).where(Series.owner_user_id == user_id, Series.kind == SeriesKind.CAST)
    ):
        if skill.id in series.character_ids_json:
            series.character_ids_json = [
                cid for cid in series.character_ids_json if cid != skill.id
            ]
    skill_library_service.delete(session, skill=skill, actor_user_id=user_id)


# ---- Per-image reference asset management --------------------------------


def append_reference_asset(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    asset_id: str,
    view: str = CharacterViewAngle.GENERAL.value,
    label: str | None = None,
) -> CharacterView:
    """Adds (or replaces) one view's reference image.

    Called both by the character library UI's per-image upload and by
    `app.workflows.nodes.execute_asset_output_link` when a generation job's
    output is auto-attached. A second image for the same non-general view
    replaces the earlier one instead of piling up near-duplicate shots of
    the same pose; `general` (freeform, no fixed pose) can accumulate up to
    the cap.
    """
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    _validate_reference_assets(session, user_id=user_id, asset_ids=[asset_id])
    payload = _payload(skill)
    entries = [e for e in _reference_assets(skill) if e.get("asset_id") != asset_id]
    if view != CharacterViewAngle.GENERAL.value:
        entries = [e for e in entries if e.get("view") != view]
    entries.append(
        {
            "asset_id": asset_id,
            "view": view,
            "label": (label or "").strip() or None,
            "created_at": utcnow().isoformat(),
        }
    )
    if len(entries) > MAX_REFERENCE_ASSETS:
        entries = entries[-MAX_REFERENCE_ASSETS:]
    payload["reference_assets"] = entries
    _set_payload(skill, payload)
    session.flush()
    return CharacterView(skill)


def update_reference_asset(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    asset_id: str,
    view: str | None = None,
    label: str | None = None,
) -> CharacterView:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    payload = _payload(skill)
    entries = _reference_assets(skill)
    found = False
    for entry in entries:
        if entry.get("asset_id") == asset_id:
            found = True
            if view is not None:
                entry["view"] = view
            if label is not None:
                entry["label"] = label.strip() or None
    if not found:
        raise NotFound("参考素材不存在。")
    payload["reference_assets"] = entries
    _set_payload(skill, payload)
    session.flush()
    return CharacterView(skill)


def remove_reference_asset(
    session: Session, *, user_id: str, character_id: str, asset_id: str
) -> CharacterView:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    payload = _payload(skill)
    payload["reference_assets"] = [
        e for e in _reference_assets(skill) if e.get("asset_id") != asset_id
    ]
    _set_payload(skill, payload)
    session.flush()
    return CharacterView(skill)


# ---- Sharing: publish a character to the skill marketplace --------------


def publish_character(
    session: Session, *, user_id: str, character_id: str, portrait_consent: bool
) -> CharacterView:
    """Shares a character to the skill marketplace, for other creators to use.

    Requires an explicit portrait/likeness consent flag on *this* call —
    sharing (and potentially selling, via `access_credits`) a character is
    publishing a depicted persona, so it cannot inherit whatever consent
    covered the original generation request. Purely private use (the skill
    stays `DRAFT`) needs none of this.
    """
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    if not portrait_consent:
        raise ValidationFailed(
            "分享角色前需要确认你有权公开这个形象。",
            fields={"portrait_consent": "必须勾选肖像/形象授权确认"},
        )
    payload = _payload(skill)
    payload["portrait_consent_at"] = utcnow().isoformat()
    _set_payload(skill, payload)
    skill_library_service.publish(session, skill=skill, actor_user_id=user_id)
    return CharacterView(skill)


def withdraw_character(session: Session, *, user_id: str, character_id: str) -> CharacterView:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    skill_library_service.withdraw(session, skill=skill, actor_user_id=user_id)
    return CharacterView(skill)


# ---- Admin/moderation projection -----------------------------------------


def admin_reference_assets(session: Session, skill: CreationSkill) -> list[dict[str, Any]]:
    """`(asset_id, view, label, url)` for every reference image on a character
    skill, for `CreationSkillAdminView`.

    Unlike `CharacterResponse`'s own projection this reads a bare
    `CreationSkill` with no ownership check — the moderation queue and the
    admin skill browser both need to see any owner's character, not just the
    caller's own. Non-character skills have nothing to project.
    """
    if skill.category != CreationSkillCategory.CHARACTER:
        return []
    return [
        {
            "asset_id": str(entry["asset_id"]),
            "view": str(entry.get("view") or CharacterViewAngle.GENERAL.value),
            "label": entry.get("label"),
            "url": media_urls.asset_url(session, str(entry["asset_id"])),
        }
        for entry in CharacterView(skill).reference_assets
        if entry.get("asset_id")
    ]


def admin_portrait_consent_at(skill: CreationSkill) -> str | None:
    """See `admin_reference_assets` — same bare-`CreationSkill` admin path."""
    if skill.category != CreationSkillCategory.CHARACTER:
        return None
    return CharacterView(skill).portrait_consent_at


# ---- Series CRUD --------------------------------------------------------


def create_series(
    session: Session,
    *,
    user_id: str,
    title: str,
    description: str | None,
    shortform_profile_key: str | None,
) -> Series:
    series = Series(
        owner_user_id=user_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        shortform_profile_key=shortform_profile_key,
        character_ids_json=[],
        kind=SeriesKind.CAST,
    )
    session.add(series)
    session.flush()
    return series


def list_series(session: Session, *, user_id: str) -> list[Series]:
    stmt = (
        select(Series)
        .where(Series.owner_user_id == user_id, Series.kind == SeriesKind.CAST)
        .order_by(Series.created_at.desc())
    )
    return list(session.scalars(stmt))


@dataclass(slots=True)
class SeriesRecency:
    episode_count: int
    latest_work: Work | None


def series_recency(session: Session, *, series_ids: list[str]) -> dict[str, SeriesRecency]:
    """Per-series episode count and most recent episode, in one query.

    Ordering within each `series_id` group puts the highest episode number
    (ties broken by publish time) first, so the first row seen per group is
    the "latest episode" the create page's recent-series rail links into.
    """
    if not series_ids:
        return {}
    works = session.scalars(
        select(Work)
        .where(Work.series_id.in_(series_ids))
        .order_by(
            Work.series_id,
            Work.episode_number.desc().nulls_last(),
            Work.published_at.desc().nulls_last(),
        )
    )
    result: dict[str, SeriesRecency] = {}
    for work in works:
        series_id = work.series_id
        if series_id is None:
            continue
        info = result.get(series_id)
        if info is None:
            result[series_id] = SeriesRecency(episode_count=1, latest_work=work)
        else:
            info.episode_count += 1
    return result


@dataclass(slots=True)
class SeriesDetail:
    series: Series
    characters: list[CharacterView]
    episodes: list[Work]
    next_episode_number: int


def get_series_detail(session: Session, *, user_id: str, series_id: str) -> SeriesDetail:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    characters: list[CharacterView] = []
    for character_id in series.character_ids_json:
        skill = session.get(CreationSkill, character_id)
        if skill is not None and skill.category == CreationSkillCategory.CHARACTER:
            characters.append(CharacterView(skill))
    episodes = list(
        session.scalars(
            select(Work)
            .where(Work.series_id == series_id)
            .order_by(Work.episode_number.asc().nulls_last())
        )
    )
    return SeriesDetail(
        series=series,
        characters=characters,
        episodes=episodes,
        next_episode_number=_next_episode_number(episodes),
    )


def _next_episode_number(episodes: list[Work]) -> int:
    numbers = [work.episode_number for work in episodes if work.episode_number is not None]
    return max(numbers, default=0) + 1


def add_character_to_series(
    session: Session, *, user_id: str, series_id: str, character_id: str
) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    _owned_character_skill(session, user_id=user_id, character_id=character_id)
    if character_id not in series.character_ids_json:
        series.character_ids_json = [*series.character_ids_json, character_id]
        session.flush()
    return series


def remove_character_from_series(
    session: Session, *, user_id: str, series_id: str, character_id: str
) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    series.character_ids_json = [cid for cid in series.character_ids_json if cid != character_id]
    session.flush()
    return series


# ---- Generation + publish wiring ----------------------------------------


def apply_character_refs(session: Session, *, user_id: str, params: dict[str, Any]) -> None:
    """Merges the selected cast's reference images and voice hints into job params.

    Called right before a job is priced and persisted (`jobs/service.py`), so
    the merged `reference_asset_ids` becomes part of what the pipeline
    actually forwards to the provider. Explicitly-uploaded reference images
    keep their slots; character references fill whatever room is left.
    """
    character_ids = params.get("character_ids") or []
    if not character_ids:
        return
    if len(character_ids) > MAX_SELECTED_CHARACTERS:
        raise ValidationFailed(
            f"最多选择 {MAX_SELECTED_CHARACTERS} 个角色。",
            fields={"params.character_ids": f"不能超过 {MAX_SELECTED_CHARACTERS} 个"},
        )

    characters = [
        CharacterView(_owned_character_skill(session, user_id=user_id, character_id=cid))
        for cid in character_ids
    ]

    merged_refs = list(params.get("reference_asset_ids") or [])
    for character in characters:
        for asset_id in character.reference_asset_ids:
            if asset_id not in merged_refs and len(merged_refs) < MAX_JOB_REFERENCE_ASSETS:
                merged_refs.append(asset_id)
    params["reference_asset_ids"] = merged_refs

    extra = dict(params.get("extra") or {})
    extra["character_voice_profiles"] = [
        {
            "character_id": character.id,
            "name": character.name,
            "voice_description": character.voice_description,
        }
        for character in characters
        if character.voice_description
    ]
    params["extra"] = extra


def assign_episode(
    session: Session,
    *,
    user_id: str,
    work: Work,
    series_id: str | None,
    episode_number: int | None,
) -> None:
    """Called at publish time. A work with no chosen series stays standalone."""
    if not series_id:
        return

    series = _owned_series(session, user_id=user_id, series_id=series_id)
    if episode_number is None:
        episode_number = get_series_detail(
            session, user_id=user_id, series_id=series_id
        ).next_episode_number

    clash = session.scalar(
        select(Work).where(Work.series_id == series.id, Work.episode_number == episode_number)
    )
    if clash is not None:
        raise Conflict(f"第 {episode_number} 集已经存在。")

    work.series_id = series.id
    work.episode_number = episode_number
