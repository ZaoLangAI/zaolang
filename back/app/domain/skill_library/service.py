"""User-authored creation skills: create, edit, share, review, discover.

A skill starts life as a private `DRAFT` — usable in the owner's own creation
flow immediately, no review needed. `publish()` is the owner opting in to
sharing: it flips `visibility` to `PUBLIC` and files the skill into the same
`moderation_queue_items` table `work`/`asset` already use (subject_type
`"skill"`), rather than a bespoke review path. A human decision on that queue
item is what calls `approve()`/`reject()` here — see
`app/api/v1/admin/content.py::decide()`.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.access import service as access_service
from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.moderation_policy import assert_allowed, text_values
from app.domain.moderation_queue import service as moderation_queue
from app.domain.skill_library import catalog as skill_catalog
from app.models import Asset, CreationSkill, ModerationQueueItem
from app.models.base import utcnow
from app.models.enums import (
    IMAGE_ASSET_SKILL_CATEGORIES,
    AssetRole,
    CharacterViewAngle,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    MediaType,
    ModerationStage,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.storage import s3

ContentType = Literal["template", "image_asset"]

MAX_DESCRIPTION_LENGTH = 300
QUEUE_STAGE = ModerationStage.SKILL_REVIEW
QUEUE_SUBJECT_TYPE = "skill"


@dataclass(slots=True)
class ListPage:
    items: list[CreationSkill]
    next_cursor: str | None
    has_more: bool


def create(
    session: Session,
    *,
    owner_user_id: str,
    title: str,
    description: str,
    category: CreationSkillCategory,
    params_json: dict[str, Any],
    cover_asset_id: str | None,
    applicable_operations: list[Operation] | None = None,
    access_credits: int = 0,
) -> CreationSkill:
    _assert_cover_owned(session, owner_user_id=owner_user_id, cover_asset_id=cover_asset_id)
    skill = CreationSkill(
        owner_user_id=owner_user_id,
        title=title,
        description=description,
        category=category,
        params_json=params_json,
        applicable_operations_json=_deduped_operations(applicable_operations),
        cover_asset_id=cover_asset_id,
        visibility=CreationSkillVisibility.PRIVATE,
        status=CreationSkillStatus.DRAFT,
        access_credits=access_service.normalize_access_credits(
            session, access_credits, actor_user_id=owner_user_id
        ),
    )
    session.add(skill)
    session.flush()
    return skill


def ensure_catalog_skills(session: Session, *, owner_user_id: str) -> list[CreationSkill]:
    """Plants `catalog.CATALOG`'s platform-curated templates and image assets.

    This is a system-default catalogue, analogous to
    `workflow_templates_service.ensure_default_templates` or
    `agent_skills_service.ensure_default_profiles` — not a user submission —
    so it skips `create()`'s owner-drafts-then-`publish()` flow entirely and
    writes straight to `PUBLISHED`/`PUBLIC`. It never opens a
    `moderation_queue_items` row and leaves `reviewed_by_user_id`/
    `reviewed_at` as `None` by design: there is no human review to record for
    a row nothing ever submitted for review.

    Idempotent and additive, matched by `(owner_user_id, title)` since
    `CreationSkill` has no dedicated catalogue-key column: a title already
    present for this owner is left untouched, so an operator's own edit to a
    previously-seeded row survives a later re-run. The one exception is
    `cover_asset_id`: a row (new or pre-existing) that still has none gets one
    backfilled from `catalog.py`'s shipped cover, but a row that already
    carries one — whether from an earlier run of this same backfill or an
    operator's own re-cover — is never touched (see `_ensure_seeded_cover`).
    Character/scene image-asset rows also get that same still copied into
    `params_json["character"|"scene"]["reference_assets"]` once the list is
    still empty (`_ensure_seeded_reference`); a non-empty list is left
    alone so an operator who replaced the demo still survives `make seed`.
    """
    existing = {
        row.title: row
        for row in session.scalars(
            select(CreationSkill).where(CreationSkill.owner_user_id == owner_user_id)
        )
    }
    created: list[CreationSkill] = []
    for item in skill_catalog.CATALOG:
        skill = existing.get(item.title)
        if skill is None:
            skill = CreationSkill(
                owner_user_id=owner_user_id,
                title=item.title,
                description=item.description,
                category=item.category,
                params_json=item.params_json(),
                applicable_operations_json=_deduped_operations(list(item.applicable_operations)),
                cover_asset_id=None,
                visibility=CreationSkillVisibility.PUBLIC,
                status=CreationSkillStatus.PUBLISHED,
                access_credits=0,
            )
            session.add(skill)
            session.flush()
            created.append(skill)
        _ensure_seeded_cover(session, skill=skill, item=item, owner_user_id=owner_user_id)
        _ensure_seeded_reference(skill, item=item)
    return created


def _ensure_seeded_cover(
    session: Session, *, skill: CreationSkill, item: skill_catalog.CatalogSkill, owner_user_id: str
) -> None:
    """Backfills a catalogue skill's cover from its shipped `seed_covers/`
    JPEG, the same "system-default, not a stand-in for real content" content
    class as the skill rows themselves (see `ensure_catalog_skills`'s
    docstring).

    A no-op once `cover_asset_id` is set, from any source — this never
    replaces a cover, so an operator swapping one out in the admin console
    survives every later `make seed`.
    """
    if skill.cover_asset_id is not None:
        return
    cover_path = item.cover_path()
    if cover_path is None:
        return

    payload = cover_path.read_bytes()
    with Image.open(io.BytesIO(payload)) as image:
        width, height = image.size

    object_key = f"seed/skill-library/{item.key}.jpg"
    s3.put_object(object_key, payload, content_type="image/jpeg")

    asset = Asset(
        owner_user_id=owner_user_id,
        object_key=object_key,
        media_type=MediaType.IMAGE,
        mime_type="image/jpeg",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=AssetRole.COVER,
        width=width,
        height=height,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        is_prototype=False,
    )
    session.add(asset)
    session.flush()
    skill.cover_asset_id = asset.id
    session.flush()


def _ensure_seeded_reference(skill: CreationSkill, *, item: skill_catalog.CatalogSkill) -> None:
    """Puts the seeded cover onto a character/scene skill's
    `reference_assets` once, so the plaza card and a later `@` apply share
    the same still. A no-op when the nested list is already non-empty —
    an operator who replaced the demo still survives `make seed`. Cover
    assets have no nested bundle."""
    cover_id = skill.cover_asset_id
    if cover_id is None:
        return
    if item.category == CreationSkillCategory.CHARACTER:
        nest_key = "character"
        view = CharacterViewAngle.FRONT.value
    elif item.category == CreationSkillCategory.SCENE_ASSET:
        nest_key = "scene"
        view = "establishing"
    else:
        return

    current = dict(skill.params_json or {})
    nested = dict(current.get(nest_key) or {}) if isinstance(current.get(nest_key), dict) else {}
    refs = nested.get("reference_assets")
    if isinstance(refs, list) and refs:
        return
    nested = {
        **nested,
        "reference_assets": [
            {
                "asset_id": cover_id,
                "view": view,
                "label": None,
                "created_at": utcnow().isoformat(),
            }
        ],
    }
    skill.params_json = {**current, nest_key: nested}


def update(
    session: Session,
    *,
    skill: CreationSkill,
    actor_user_id: str,
    title: str,
    description: str,
    category: CreationSkillCategory,
    params_json: dict[str, Any],
    cover_asset_id: str | None,
    applicable_operations: list[Operation] | None = None,
) -> CreationSkill:
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能编辑自己创建的技能。")

    _assert_cover_owned(session, owner_user_id=actor_user_id, cover_asset_id=cover_asset_id)

    skill.title = title
    skill.description = description
    skill.category = category
    skill.params_json = params_json
    skill.applicable_operations_json = _deduped_operations(applicable_operations)
    skill.cover_asset_id = cover_asset_id

    # 已公开或正在审核的技能一旦改动内容，视为撤回分享——必须重新走 publish()。
    if skill.status != CreationSkillStatus.DRAFT:
        _unpublish(skill)

    session.flush()
    return skill


def update_pricing(
    session: Session, *, skill: CreationSkill, actor_user_id: str, access_credits: int
) -> CreationSkill:
    """Change only the unlock price. Does not unpublish or re-queue review."""
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能修改自己创建的技能。")
    skill.access_credits = access_service.normalize_access_credits(
        session, access_credits, actor_user_id=actor_user_id
    )
    session.flush()
    return skill


def withdraw(session: Session, *, skill: CreationSkill, actor_user_id: str) -> CreationSkill:
    """Owner takes a shared skill back to private, at any point in its lifecycle."""
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能撤回自己创建的技能。")
    _unpublish(skill)
    _resolve_open_queue_item(session, skill)
    session.flush()
    return skill


def publish(session: Session, *, skill: CreationSkill, actor_user_id: str) -> CreationSkill:
    """Owner asks to share this skill; files it for human review."""
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能分享自己创建的技能。")
    if skill.status == CreationSkillStatus.PENDING_REVIEW:
        return skill
    if skill.status == CreationSkillStatus.PUBLISHED:
        return skill

    assert_allowed(
        session,
        config_key="skill_moderation",
        texts=[skill.title, skill.description, *text_values(skill.params_json)],
        user_id=actor_user_id,
        subject_type="skill",
    )

    skill.visibility = CreationSkillVisibility.PUBLIC
    skill.status = CreationSkillStatus.PENDING_REVIEW
    skill.reject_reason = None
    _reopen_queue_item(session, skill)
    session.flush()
    return skill


def delete(session: Session, *, skill: CreationSkill, actor_user_id: str) -> None:
    """Owner removes a skill for good, at any status.

    Unlike a work, a skill carries no downstream lineage: whoever already
    applied it copied its params into their own draft/job at that moment, so
    deleting the row here cannot orphan anything that resolves it live.
    """
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能删除自己创建的技能。")

    queue_item = _queue_item_for(session, skill)
    if queue_item is not None:
        session.delete(queue_item)
    session.delete(skill)
    session.flush()


def get_owned(session: Session, *, skill_id: str, owner_user_id: str) -> CreationSkill:
    skill = session.get(CreationSkill, skill_id)
    if skill is None or skill.owner_user_id != owner_user_id:
        raise NotFound("技能不存在。")
    return skill


def get_usable(session: Session, *, skill_id: str, viewer_id: str | None) -> CreationSkill:
    """A published skill is visible to anyone; drafts stay owner-only.

    Visibility here is "can see the card / detail shell", not "can fold
    params into a job". Paid apply is gated by `assert_unlocked_for_use`.
    """
    skill = session.get(CreationSkill, skill_id)
    if skill is None:
        raise NotFound("技能不存在。")
    if skill.status == CreationSkillStatus.PUBLISHED:
        return skill
    if viewer_id is not None and skill.owner_user_id == viewer_id:
        return skill
    raise NotFound("技能不存在。")


def viewer_has_access(session: Session, skill: CreationSkill, viewer_id: str | None) -> bool:
    return access_service.viewer_unlocked_skill(session, skill, viewer_id)


def asset_is_usable_skill_reference(
    session: Session, *, asset: Asset, viewer_id: str | None
) -> bool:
    """A published marketplace skill's public cover may be sent as a
    generation reference by anyone who can use that skill — the still is
    already `PUBLIC_VIEW_ONLY`, and attaching it is how an image-asset
    recipe becomes an img2img reference without cloning the row into the
    viewer's own roster."""
    if asset.media_type != MediaType.IMAGE:
        return False
    if asset.visibility == Visibility.PRIVATE:
        return False
    skill = session.scalar(
        select(CreationSkill).where(
            CreationSkill.cover_asset_id == asset.id,
            CreationSkill.status == CreationSkillStatus.PUBLISHED,
            CreationSkill.visibility == CreationSkillVisibility.PUBLIC,
        )
    )
    if skill is None:
        return False
    return viewer_has_access(session, skill, viewer_id)


def assert_unlocked_for_use(session: Session, skill: CreationSkill, viewer_id: str | None) -> None:
    access_service.assert_skill_unlocked(session, skill, viewer_id)


def record_usage(session: Session, *, skill: CreationSkill) -> CreationSkill:
    skill.usage_count += 1
    session.flush()
    return skill


def list_mine(session: Session, *, owner_user_id: str, limit: int = 60) -> ListPage:
    """The generic "我的技能" tab (`ManageSkillDialog`-backed) only knows how
    to edit the flat `prompt`/`aspect_ratio`/... template shape — an
    `IMAGE_ASSET_SKILL_CATEGORIES` skill (character/scene_asset/cover_asset)
    is always excluded here in favor of its dedicated maintenance page
    (`/create/characters`, `/create/scenes`), same as `list_public`'s default
    landing view."""
    stmt = (
        select(CreationSkill)
        .where(
            CreationSkill.owner_user_id == owner_user_id,
            CreationSkill.category.notin_(IMAGE_ASSET_SKILL_CATEGORIES),
        )
        .order_by(CreationSkill.created_at.desc(), CreationSkill.id.desc())
        .limit(limit + 1)
    )
    rows = list(session.scalars(stmt))
    has_more = len(rows) > limit
    return ListPage(items=rows[:limit], next_cursor=None, has_more=has_more)


def list_public(
    session: Session,
    *,
    category: CreationSkillCategory | None = None,
    content_type: ContentType | None = None,
    access: str | None = None,
    cursor: str | None = None,
    limit: int = 24,
) -> ListPage:
    """Browses published skills for the marketplace.

    `category` (an exact match) always wins when given. Otherwise
    `content_type` picks a side of the marketplace's two-tier filter: a
    "template" (`scene`/`lens`/`style`/`format`/`other`, `SkillCard`-rendered from
    flat `prompt`/`aspect_ratio`/... params) or an "image_asset" (`character`
    /`scene_asset`/`cover_asset`, each purchasable but not template-shaped —
    see `IMAGE_ASSET_SKILL_CATEGORIES`). `None` (the plaza's default landing
    view, same as before this parameter existed) behaves like `"template"`.
    """
    anchor: CreationSkill | None = None
    if cursor:
        anchor = session.get(CreationSkill, cursor)
        if anchor is None or anchor.status != CreationSkillStatus.PUBLISHED:
            return ListPage(items=[], next_cursor=None, has_more=False)

    stmt = select(CreationSkill).where(CreationSkill.status == CreationSkillStatus.PUBLISHED)
    if category:
        stmt = stmt.where(CreationSkill.category == category)
    elif content_type == "image_asset":
        stmt = stmt.where(CreationSkill.category.in_(IMAGE_ASSET_SKILL_CATEGORIES))
    else:
        stmt = stmt.where(CreationSkill.category.notin_(IMAGE_ASSET_SKILL_CATEGORIES))
    if access == "free":
        stmt = stmt.where(CreationSkill.access_credits == 0)
    elif access == "paid":
        stmt = stmt.where(CreationSkill.access_credits > 0)
    stmt = stmt.order_by(CreationSkill.created_at.desc(), CreationSkill.id.desc())
    if anchor is not None:
        stmt = stmt.where(
            (CreationSkill.created_at < anchor.created_at)
            | ((CreationSkill.created_at == anchor.created_at) & (CreationSkill.id < anchor.id))
        )

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]
    return ListPage(
        items=items, next_cursor=items[-1].id if has_more and items else None, has_more=has_more
    )


def admin_list(
    session: Session, *, status: CreationSkillStatus | None = None, limit: int = 50
) -> list[CreationSkill]:
    """Global browse for the ops console — `None` means every status, not
    just pending review (that narrower view is the moderation queue's job)."""
    stmt = select(CreationSkill).order_by(CreationSkill.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(CreationSkill.status == status)
    return list(session.scalars(stmt))


def approve(session: Session, *, skill: CreationSkill, reviewer_user_id: str) -> CreationSkill:
    if skill.status != CreationSkillStatus.PENDING_REVIEW:
        raise Conflict("只能对待审核技能做出审核决定。")

    skill.status = CreationSkillStatus.PUBLISHED
    skill.reviewed_by_user_id = reviewer_user_id
    skill.reviewed_at = utcnow()
    skill.reject_reason = None
    session.flush()
    return skill


def reject(
    session: Session, *, skill: CreationSkill, reviewer_user_id: str, reason: str
) -> CreationSkill:
    if skill.status != CreationSkillStatus.PENDING_REVIEW:
        raise Conflict("只能对待审核技能做出审核决定。")
    if not reason.strip():
        raise ValidationFailed("拒绝必须填写理由。")

    skill.status = CreationSkillStatus.REJECTED
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reviewed_by_user_id = reviewer_user_id
    skill.reviewed_at = utcnow()
    skill.reject_reason = reason
    session.flush()
    return skill


def admin_takedown(
    session: Session, *, skill: CreationSkill, actor_user_id: str, reason: str
) -> CreationSkill:
    """Operator force-unpublishes a skill that already cleared review.

    Unlike `reject()` this does not require `PENDING_REVIEW` — a takedown can
    hit a skill at any point after it went live.
    """
    if not reason.strip():
        raise ValidationFailed("下架必须填写理由。")

    skill.status = CreationSkillStatus.REJECTED
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reject_reason = reason
    skill.reviewed_by_user_id = actor_user_id
    skill.reviewed_at = utcnow()
    session.flush()
    return skill


def _unpublish(skill: CreationSkill) -> None:
    skill.status = CreationSkillStatus.DRAFT
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reject_reason = None


def _queue_item_for(session: Session, skill: CreationSkill) -> ModerationQueueItem | None:
    """At most one row can ever exist per (subject_type, subject_id, stage) —
    `uq_moderation_queue_subject` has no `status` in its key — so a skill's
    review history lives in one row that gets reopened, not appended to."""
    return session.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == QUEUE_SUBJECT_TYPE,
            ModerationQueueItem.subject_id == skill.id,
            ModerationQueueItem.stage == QUEUE_STAGE,
        )
    )


def _reopen_queue_item(session: Session, skill: CreationSkill) -> None:
    moderation_queue.enqueue_for_review(
        session,
        subject_type=QUEUE_SUBJECT_TYPE,
        subject_id=skill.id,
        stage=QUEUE_STAGE,
        reason_code=None,
    )


def _resolve_open_queue_item(session: Session, skill: CreationSkill) -> None:
    """Owner-initiated withdrawal closes a queue item still awaiting review."""
    item = _queue_item_for(session, skill)
    if item is not None and item.status == ModerationStatus.NEEDS_REVIEW:
        item.status = ModerationStatus.REJECTED
        item.resolved_at = utcnow()
        item.reason_code = "withdrawn_by_owner"


def _deduped_operations(operations: list[Operation] | None) -> list[str]:
    return list(dict.fromkeys(op.value for op in (operations or [])))


# `app.agents.copywriter`'s enhance coach diagnoses these video dimensions
# (see its `VIDEO_DIMENSIONS`) and has no tool access to the skill library
# itself — matching happens here, in code, after the coach's JSON contract
# already ran. Keyed by the diagnosis dimension, valued by the `key` prefix
# `catalog.CATALOG`'s `format` rows use for that same writing axis. `scene`
# and `mood` have no entry: `format` rows constrain *how a shot is written*,
# not what the scene contains or how it feels, so neither dimension maps
# onto a single writing axis in the catalogue.
_FORMAT_SKILL_KEY_PREFIXES_BY_DIMENSION: dict[str, str] = {
    "subject": "fmt-frame-",
    "camera": "fmt-camera-",
    "action": "fmt-action-",
    "lighting": "fmt-light-",
    "pacing": "fmt-transition-",
}

# `CatalogSkill.key` is a catalogue-only identifier — `ensure_catalog_skills`
# never persists it onto `CreationSkill` (no dedicated column for it; see
# that function's own docstring) — so a title, not a key, is the only thing
# that survives into the database to match against. Computed once from the
# catalogue rather than hand-duplicated, so a renamed `format` entry cannot
# silently fall out of this mapping.
_FORMAT_SKILL_TITLES_BY_DIMENSION: dict[str, frozenset[str]] = {
    dimension: frozenset(
        item.title for item in skill_catalog.CATALOG if item.key.startswith(prefix)
    )
    for dimension, prefix in _FORMAT_SKILL_KEY_PREFIXES_BY_DIMENSION.items()
}

MAX_AUTO_APPLIED_FORMAT_SKILLS = 2


def apply_matching_format_skills(
    session: Session,
    *,
    operation: str,
    dimensions: Sequence[Mapping[str, str]],
    prompt: str,
    max_length: int,
    limit: int = MAX_AUTO_APPLIED_FORMAT_SKILLS,
) -> tuple[str, list[dict[str, str]]]:
    """Auto-attaches up to `limit` published `format` skills whose rule
    matches a dimension the enhance coach just flagged `missing`/`weak` —
    the same rule a user would otherwise have to find and apply by hand from
    the prompt library (`front/src/features/canvas/prompt-library-panel.tsx`).

    Every seeded `format` row is video-only (`applicable_operations_json`
    only ever carries the three video operations), so an image polish
    (`asset_kind` character/scene/cover, or any `text_to_image`/
    `image_to_image` call) always gets back `(prompt, [])` unchanged —
    `operation not in row.applicable_operations_json` filters every
    candidate out before a title ever reaches the query.

    Picks in the diagnosis's own dimension order, at most one skill per
    dimension, skipping a candidate whose `prompt_suffix` is already present
    in `prompt` or would push it past `max_length` — appending is not worth
    truncating a hard-won rewrite mid-rule.
    """
    if not operation or limit <= 0:
        return prompt, []

    ordered_dimensions: list[str] = []
    candidate_titles: set[str] = set()
    for entry in dimensions:
        key = str(entry.get("key") or "")
        status = str(entry.get("status") or "")
        titles = _FORMAT_SKILL_TITLES_BY_DIMENSION.get(key)
        if not titles or status not in ("missing", "weak") or key in ordered_dimensions:
            continue
        ordered_dimensions.append(key)
        candidate_titles |= titles
    if not candidate_titles:
        return prompt, []

    rows_by_title = {
        row.title: row
        for row in session.scalars(
            select(CreationSkill).where(
                CreationSkill.category == CreationSkillCategory.FORMAT,
                CreationSkill.status == CreationSkillStatus.PUBLISHED,
                CreationSkill.visibility == CreationSkillVisibility.PUBLIC,
                CreationSkill.title.in_(candidate_titles),
            )
        )
    }

    updated = prompt
    applied: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for key in ordered_dimensions:
        if len(applied) >= limit:
            break
        for title in sorted(_FORMAT_SKILL_TITLES_BY_DIMENSION[key]):
            row = rows_by_title.get(title)
            if row is None or row.id in seen_ids:
                continue
            if operation not in row.applicable_operations_json:
                continue
            suffix = str((row.params_json or {}).get("prompt_suffix") or "").strip()
            if not suffix or suffix in updated:
                continue
            candidate = f"{updated}，{suffix}" if updated else suffix
            if len(candidate) > max_length:
                continue
            updated = candidate
            applied.append({"id": row.id, "title": row.title})
            seen_ids.add(row.id)
            break
    return updated, applied


# Every seeded `drama` row's title, taken from the catalogue at import time
# for the same reason `_FORMAT_SKILL_TITLES_BY_DIMENSION` is: `CatalogSkill.key`
# is never persisted, so `title` is the only handle the DB side has, and
# deriving the set from `CATALOG` means a catalogue rename can't silently
# shrink what the matcher can see.
#
# Scoping the candidate list to seeded rows (rather than every published
# `drama` skill) is deliberate: these two functions deliberately skip
# `assert_unlocked_for_use` and `record_usage`, which is only defensible
# because the catalogue is free, public and factory-owned. A user-authored
# paid `drama` skill must not be handed to an agent behind its author's back.
_CATALOG_DRAMA_TITLES: frozenset[str] = frozenset(
    item.title
    for item in skill_catalog.CATALOG
    if item.category == CreationSkillCategory.DRAMA
)


def list_drama_candidates(session: Session) -> list[tuple[str, str]]:
    """`(id, title)` for every seeded `drama` skill, title-sorted.

    Titles only: this is the shortlist `app.agents.skill_matcher` shows a
    cheap model, and descriptions would multiply its prompt size by roughly
    eight for a decision the title alone already supports. The picked rows'
    descriptions are loaded separately by `load_reference_skills`.
    """
    rows = session.scalars(
        select(CreationSkill).where(
            CreationSkill.category == CreationSkillCategory.DRAMA,
            CreationSkill.status == CreationSkillStatus.PUBLISHED,
            CreationSkill.visibility == CreationSkillVisibility.PUBLIC,
            CreationSkill.title.in_(_CATALOG_DRAMA_TITLES),
        )
    )
    return sorted(((row.id, row.title) for row in rows), key=lambda pair: pair[1])


def load_reference_skills(session: Session, skill_ids: Sequence[str]) -> list[dict[str, str]]:
    """`{id, title, description}` for auto-matched reference skills, in the
    order asked for.

    Deliberately *not* `_resolve_referenced_skills`'s path
    (`app.domain.script_writing.service`): that one is for skills the user
    picked, so it charges access and bumps `usage_count`. A row this
    function returns was chosen by a model on the user's behalf, and
    counting that as usage would let the matcher rewrite the marketplace's
    「热门」ranking one polish at a time.
    """
    ids = list(dict.fromkeys(skill_ids))
    if not ids:
        return []
    rows = {
        row.id: row
        for row in session.scalars(
            select(CreationSkill).where(
                CreationSkill.id.in_(ids),
                CreationSkill.status == CreationSkillStatus.PUBLISHED,
                CreationSkill.visibility == CreationSkillVisibility.PUBLIC,
            )
        )
    }
    return [
        {"id": row.id, "title": row.title, "description": row.description or ""}
        for row in (rows.get(skill_id) for skill_id in ids)
        if row is not None
    ]


def _assert_cover_owned(
    session: Session, *, owner_user_id: str, cover_asset_id: str | None
) -> None:
    if not cover_asset_id:
        return
    asset = session.get(Asset, cover_asset_id)
    if asset is None or asset.owner_user_id != owner_user_id:
        raise ValidationFailed("素材不存在或不属于当前用户。", asset_id=cover_asset_id)
