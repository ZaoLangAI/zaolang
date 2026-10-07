"""Character library: reusable cast members for generation and drama scripts.

A character is a reusable cast member: a name, up to a few reference images
and a text voice description — stored as a `CreationSkill` with
`category=CHARACTER` rather than a bespoke table (see `CharacterView` below
for why callers never need to know that).

The `Series(kind=cast)` roster CRUD that used to live in this module
(`create_series`/`list_series`/`get_series_detail`/`assign_episode`/...) was
removed with the old single-clip `ShortformStudio` it only ever served —
short-drama series management now lives entirely under
`app.domain.editor.service`'s `Series(kind=drama)` path (see
`.cursor/skills/zaolang-editor-drama`). Every remaining `Series` creation path
passes `kind=drama` explicitly, and the leftover `kind=cast` rows this used to
scan for on every `delete_character` call have been purged by migration
`ada14f32676f` — there is nothing left for that cleanup loop to do.

Nothing here talks to a TTS or face-consistency provider directly.
`voice_description` and reference images are carried through to the job so
the media endpoint selected from Models has something to match against.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import partial
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.asset_variants import service as asset_variants_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.image_assets import camera as camera_vocab
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, SkillAssetVariant
from app.models.base import utcnow
from app.models.enums import (
    AssetEntryType,
    CharacterViewAngle,
    CreationSkillCategory,
    MediaType,
)
from app.presenters import media_urls

# A flat `reference_asset_ids` list (create/PATCH) fills one look — the
# per-look entry cap (`asset_variants.service`). Looks themselves hold the
# rest; nothing is silently evicted any more.
MAX_REFERENCE_ASSETS = asset_variants_service.MAX_ENTRIES_PER_VARIANT
# Default per-character subset a job gets when the caller picked nothing.
MAX_DEFAULT_JOB_REFERENCES = asset_variants_service.MAX_DEFAULT_CHARACTER_REFERENCES
# Mirrors GenerationParams.reference_asset_ids / character_ids in jobs.py —
# kept here too so a validation error names the right limit before a job ever
# reaches the API schema.
MAX_JOB_REFERENCE_ASSETS = 9
MAX_SELECTED_CHARACTERS = 4
# `action_clips` is an accumulating list (no "one per view" replacement rule
# like `reference_assets`' non-general views) — a generous but bounded cap.
MAX_ACTION_CLIPS = 12

# Sub-key inside `CreationSkill.params_json` a character skill's structured
# data lives under, kept apart from the generic `prompt`/`prompt_suffix`/
# `aspect_ratio` keys other skill categories use (see
# `app.workflows.nodes.execute_skill_context`).
CHARACTER_PARAMS_KEY = "character"
# Sub-key holding this character's generated video clips
# (`{"asset_id", "label", "created_at"}`), written by
# `app.workflows.nodes._link_character_action_output` for a succeeded
# `video_asset_kind=character_action` job. Deliberately separate from
# `reference_assets` above, not a video-typed entry inside it: every entry
# in `reference_assets` flows unfiltered into a *future* job's
# `reference_asset_ids` via `apply_character_refs` below, and that path must
# never hand a video clip to a plain image generation call as if it were a
# still reference.
CHARACTER_ACTION_CLIPS_KEY = "action_clips"

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
        """The P0-shaped projection of the card's looks
        (`asset_variants.service.project`)."""
        return asset_variants_service.project(self.skill)

    @property
    def reference_asset_ids(self) -> list[str]:
        return [str(entry["asset_id"]) for entry in self.reference_assets if entry.get("asset_id")]

    @property
    def action_clips(self) -> list[dict[str, Any]]:
        """Generated `character_action` video clips — see `CHARACTER_ACTION_CLIPS_KEY`.

        Deliberately not merged into `reference_assets`/`reference_asset_ids`
        above: those feed `apply_character_refs`, which must never hand a
        video clip to a plain image-generation job as a still reference.
        """
        return list(_action_clips(self.skill))

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


def _action_clips(skill: CreationSkill) -> list[dict[str, Any]]:
    """Copies of each `action_clips` entry — same copy-not-reference
    contract as `_reference_assets` (see `_payload`'s docstring)."""
    raw = _payload(skill).get(CHARACTER_ACTION_CLIPS_KEY)
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


_EXPRESSION_LABEL_PREFIX = "表情"


def default_reference_asset_ids(
    character: CharacterView, variant_id: str | None = None
) -> list[str]:
    """What a job gets for this character when the caller picked no images:
    the default look (or `variant_id`'s look) subset — see
    `asset_variants.service.default_subset`. Other looks and expression
    sheets only go in when picked, so a 婚礼 sheet never sneaks into a 日常
    scene."""
    variant = (
        asset_variants_service.find_variant(character.skill, variant_id) if variant_id else None
    )
    return asset_variants_service.default_subset(character.skill, variant)


def reference_entry(character: CharacterView, asset_id: str) -> dict[str, Any] | None:
    return next((e for e in character.reference_assets if e.get("asset_id") == asset_id), None)


def _legacy_entry_type(view: str, label: str | None) -> tuple[str, str | None]:
    """P0 `(view, label)` → `(entry_type, view)`."""
    if label and label.startswith(_EXPRESSION_LABEL_PREFIX):
        return AssetEntryType.EXPRESSION_SHEET.value, None
    if view == CharacterViewAngle.FRONT.value:
        return AssetEntryType.CHARACTER_SHEET.value, CharacterViewAngle.FRONT.value
    if view in (CharacterViewAngle.SIDE.value, CharacterViewAngle.BACK.value):
        return AssetEntryType.VIEW.value, view
    return AssetEntryType.OTHER.value, None


def _legacy_variant_name(label: str | None) -> str | None:
    """P0 used a non-expression `label` as the outfit name."""
    if label and not label.startswith(_EXPRESSION_LABEL_PREFIX):
        return label
    return None


# ---- Character CRUD (adapter over the skill library) --------------------


def find_owned_character_by_name(
    session: Session, *, user_id: str, name: str
) -> CharacterView | None:
    """The owner's character whose title equals `name.strip()`, if any.

    Historical rows could share a title before the partial unique index
    landed — the newest `created_at` wins so auto-attach and the script
    studio's same-name skip both land on one card instead of flipping
    between twins.
    """
    title = name.strip()
    if not title:
        return None
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == user_id,
            CreationSkill.category == CreationSkillCategory.CHARACTER,
            CreationSkill.title == title,
        )
        .order_by(CreationSkill.created_at.desc())
        .limit(1)
    )
    skill = session.scalars(stmt).first()
    return CharacterView(skill) if skill else None


def _require_unique_character_name(
    session: Session, *, user_id: str, name: str, exclude_id: str | None = None
) -> str:
    title = name.strip()
    existing = find_owned_character_by_name(session, user_id=user_id, name=title)
    if existing is not None and existing.id != exclude_id:
        raise ValidationFailed("角色名称已存在。", fields={"name": "角色名称已存在"})
    return title


def create_character(
    session: Session,
    *,
    user_id: str,
    name: str,
    description: str | None,
    reference_asset_ids: list[str],
    voice_description: str | None,
) -> CharacterView:
    title = _require_unique_character_name(session, user_id=user_id, name=name)
    refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
    clean_description = (description or "").strip() or None
    skill = skill_library_service.create(
        session,
        owner_user_id=user_id,
        title=title,
        description=_short_description(clean_description),
        category=CreationSkillCategory.CHARACTER,
        params_json={
            CHARACTER_PARAMS_KEY: {
                "description": clean_description,
                "voice_description": (voice_description or "").strip() or None,
            }
        },
        cover_asset_id=None,
    )
    asset_variants_service.ensure_default(session, skill)
    asset_variants_service.set_members(session, skill, refs)
    return CharacterView(skill)


def list_characters(session: Session, *, user_id: str) -> list[CharacterView]:
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == user_id,
            CreationSkill.category == CreationSkillCategory.CHARACTER,
        )
        # One round trip for every card's looks and images, not one per card.
        .options(selectinload(CreationSkill.asset_variants).selectinload(SkillAssetVariant.entries))
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
        skill.title = _require_unique_character_name(
            session, user_id=user_id, name=name, exclude_id=skill.id
        )
    if description is not None:
        clean = description.strip() or None
        payload["description"] = clean
        skill.description = _short_description(clean)
    if voice_description is not None:
        payload["voice_description"] = voice_description.strip() or None
    _set_payload(skill, payload)
    if reference_asset_ids is not None:
        refs = _validate_reference_assets(session, user_id=user_id, asset_ids=reference_asset_ids)
        asset_variants_service.set_members(session, skill, refs)
    # Editing a shared skill's content withdraws it from the marketplace
    # until the owner re-publishes — same rule as any other `CreationSkill`
    # (`skill_library.service.update`); a character swapped mid-share must
    # not keep showing a buyer stale claims about what they are getting.
    skill_library_service.withdraw_after_edit(session, skill)
    session.flush()
    return CharacterView(skill)


def delete_character(session: Session, *, user_id: str, character_id: str) -> None:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
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
    source_job_id: str | None = None,
    variant_id: str | None = None,
    expressions: list[str] | None = None,
    generated: bool = False,
    portrait: bool = False,
    entry_type: str | None = None,
    copy_from_entry_id: str | None = None,
    camera: dict[str, Any] | None = None,
    consistency: asset_variants_service.PendingConsistency | None = None,
) -> CharacterView:
    """Files one image under a look — the P0 `(view, label)` call shape,
    translated: a non-expression `label` names the look (created on first
    use), `表情·…` marks an expression sheet in the default look, and the
    view picks the entry type. A sheet or single view replaces the same
    slot in that look (one front sheet per outfit); extras accumulate up to
    the look's cap (422 beyond it). The first sheet becomes the card's
    anchor when it has none. `variant_id` (a look of this card) wins over the
    label; a stale one falls back to the label/default. `expressions` names
    an expression sheet's faces.

    `portrait` files an identity portrait (定妆照) — one face for the
    whole card, so always in the default look; once approved it takes the
    anchor from a sheet (`asset_variants.service.prefer_portrait_anchor`).

    `generated` (a job's write-back) never replaces: an image for a slot
    that already holds an approved one (the look's front sheet, a view, the
    same set of expressions) is kept as a candidate beside it
    (`asset_variants.service.file_generated`) for the owner to approve.

    P6 write-back overrides: `copy_from_entry_id` (调整修改) files the image
    exactly like that entry of this card — same look, type, view and
    expressions; `entry_type` (派生) sets the type outright.

    `camera` (多机位, AC-2) files a single view drawn from that pose: entry
    type `view`, the coarse view it stands for, and one slot per pose.

    Called by the character library UI and by
    `app.workflows.nodes.execute_asset_output_link`.
    """
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    _validate_reference_assets(session, user_id=user_id, asset_ids=[asset_id])
    clean_label = (label or "").strip() or None
    output_type = entry_type
    entry_type, entry_view = _legacy_entry_type(view, clean_label)
    variant = (
        asset_variants_service.find_variant(skill, variant_id) if variant_id else None
    ) or asset_variants_service.find_or_create_variant(
        session, skill, name=_legacy_variant_name(clean_label)
    )
    pose = camera_vocab.parse(camera)
    if pose is not None:
        entry_type, entry_view = AssetEntryType.VIEW.value, camera_vocab.coarse_view(pose)
    if expressions:
        entry_type, entry_view = AssetEntryType.EXPRESSION_SHEET.value, None
    if portrait:
        entry_type, entry_view = AssetEntryType.IDENTITY_PORTRAIT.value, None
        variant = asset_variants_service.ensure_default(session, skill)
    source = (
        asset_variants_service.find_entry(skill, copy_from_entry_id) if copy_from_entry_id else None
    )
    if source is not None:
        variant = source.variant
        entry_type, entry_view = source.entry_type, source.view
        expressions = list(source.expressions_json or []) or None
    elif output_type:
        entry_type, entry_view = output_type, None
    if (
        not generated
        and pose is None
        and entry_type in (AssetEntryType.CHARACTER_SHEET, AssetEntryType.VIEW)
    ):
        for stale in [
            e
            for e in variant.entries
            if e.entry_type == entry_type and e.view == entry_view and e.asset_id != asset_id
        ]:
            variant.entries.remove(stale)
        session.flush()
    if generated and source is not None:
        # An adjust is a new version of `source`: always a candidate.
        entry = asset_variants_service.file_generated(
            session,
            skill,
            variant,
            asset_id=asset_id,
            entry_type=entry_type,
            view=entry_view,
            expressions=list(source.expressions_json or []) or None,
            source_job_id=source_job_id,
            candidate=True,
            camera=source.camera_json,
            consistency=consistency,
        )
        asset_variants_service.claim_anchor(session, skill, entry)
        return CharacterView(skill)
    file = (
        partial(asset_variants_service.file_generated, consistency=consistency)
        if generated
        else asset_variants_service.add_entry
    )
    entry = file(
        session,
        skill,
        variant,
        asset_id=asset_id,
        entry_type=entry_type,
        view=entry_view,
        label=clean_label if entry_type == AssetEntryType.EXPRESSION_SHEET else None,
        expressions=expressions,
        source_job_id=source_job_id,
        camera=pose.as_dict()
        if pose is not None and source is None and entry_type == AssetEntryType.VIEW
        else None,
    )
    asset_variants_service.claim_anchor(session, skill, entry)
    return CharacterView(skill)


def append_action_clip(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    asset_id: str,
    label: str | None = None,
) -> CharacterView:
    """Adds one generated video clip to the character's `action_clips` list.

    Called by `app.workflows.nodes._link_character_action_output` when a
    `video_asset_kind=character_action` job succeeds. Unlike
    `append_reference_asset`, this always accumulates (no "one per view"
    replacement — a character has no fixed set of named action shots) up to
    `MAX_ACTION_CLIPS`, dropping the oldest entry once full.
    """
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != user_id:
        raise NotFound("视频素材不存在。")
    if asset.media_type != MediaType.VIDEO:
        raise ValidationFailed("动作片段必须是视频。", fields={"asset_id": "必须是视频素材"})
    payload = _payload(skill)
    entries = [e for e in _action_clips(skill) if e.get("asset_id") != asset_id]
    entries.append(
        {
            "asset_id": asset_id,
            "label": (label or "").strip() or None,
            "created_at": utcnow().isoformat(),
        }
    )
    if len(entries) > MAX_ACTION_CLIPS:
        entries = entries[-MAX_ACTION_CLIPS:]
    payload[CHARACTER_ACTION_CLIPS_KEY] = entries
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
    """The P0 per-image edit: a new `view` retypes the entry, a new `label`
    moves it to the look of that name (blank → the default look)."""
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    current = next(
        (e for e in asset_variants_service.entries(skill) if e.asset_id == asset_id), None
    )
    if current is None:
        raise NotFound("参考素材不存在。")
    projected = reference_entry(CharacterView(skill), asset_id) or {}
    new_view = view if view is not None else str(projected.get("view") or "general")
    new_label = label.strip() or None if label is not None else projected.get("label")
    was_anchor = current.is_anchor
    asset_variants_service.remove_asset(session, skill, asset_id)
    append_reference_asset(
        session,
        user_id=user_id,
        character_id=character_id,
        asset_id=asset_id,
        view=new_view,
        label=new_label,
    )
    if was_anchor:
        moved = next(
            (e for e in asset_variants_service.entries(skill) if e.asset_id == asset_id), None
        )
        asset_variants_service.set_anchor(session, skill, moved)
    return CharacterView(skill)


def remove_reference_asset(
    session: Session, *, user_id: str, character_id: str, asset_id: str
) -> CharacterView:
    skill = _owned_character_skill(session, user_id=user_id, character_id=character_id)
    asset_variants_service.remove_asset(session, skill, asset_id)
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


# ---- Generation + publish wiring ----------------------------------------


def apply_character_refs(
    session: Session,
    *,
    user_id: str,
    params: dict[str, Any],
    hints: asset_variants_service.ReferenceHints | None = None,
) -> None:
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
    selection = _selection_items(params, characters)

    merged_refs = list(params.get("reference_asset_ids") or [])
    for character in characters:
        item = selection.get(character.id)
        picked = asset_variants_service.select_assets(
            character.skill,
            variant_id=item.get("variant_id") if item else None,
            asset_ids=list(item.get("asset_ids") or []) if item else None,
            owner=f"角色「{character.name}」",
            field="params.character_ref_selection",
            hints=hints,
        )
        for asset_id in picked:
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


def _selection_items(
    params: dict[str, Any], characters: list[CharacterView]
) -> dict[str, dict[str, Any]]:
    """`character_ref_selection` keyed by character id; every named
    character must be one of this job's `character_ids`."""
    raw = params.get("character_ref_selection") or []
    if not isinstance(raw, list):
        return {}
    known = {character.id for character in characters}
    items: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        character_id = str(item.get("character_id") or "")
        if character_id not in known:
            raise ValidationFailed(
                "所选参考图的角色不在本次选择的角色中。",
                fields={"params.character_ref_selection": "角色必须同时出现在 character_ids"},
            )
        items[character_id] = item
    return items
