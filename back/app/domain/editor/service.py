"""Ownership, revisions, plans and variants for the drama editor."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.editor import commands as command_codec
from app.domain.editor import document as docs
from app.domain.editor import flags as editor_flags
from app.domain.editor import leases as lease_service
from app.domain.editor import state_machine
from app.domain.editor.time import ticks_from_ms
from app.domain.errors import (
    Conflict,
    Forbidden,
    NotFound,
    RevisionConflict,
    ValidationFailed,
)
from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    Draft,
    DramaEpisode,
    EditorCommandEvent,
    EditorExport,
    EditorLease,
    EditorOperationEvent,
    EditPlan,
    EpisodeContentLink,
    EpisodeCut,
    EpisodeScriptTurn,
    GenerationJob,
    Series,
    Work,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    DeliveryVariantStatus,
    DistributionChannel,
    DramaEpisodeStatus,
    EditorCommandEventStatus,
    EditPlanStatus,
    EpisodeContentRole,
    EpisodeContentType,
    EpisodeCutKind,
    EpisodeCutStatus,
    EpisodeKind,
    JobStatus,
    SeriesGenre,
    SeriesKind,
    SeriesStatus,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import ShortformConfig
from app.realtime import publisher


def _owned_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = session.get(Series, series_id)
    if series is None or series.owner_user_id != user_id:
        raise NotFound("剧集不存在。")
    return series


def _owned_episode(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    episode = session.get(DramaEpisode, episode_id)
    if episode is None:
        raise NotFound("剧集分集不存在。")
    _owned_series(session, user_id=user_id, series_id=episode.series_id)
    return episode


def _owned_cut(session: Session, *, user_id: str, cut_id: str) -> EpisodeCut:
    cut = session.get(EpisodeCut, cut_id)
    if cut is None:
        raise NotFound("剪辑不存在。")
    _owned_episode(session, user_id=user_id, episode_id=cut.episode_id)
    return cut


def require_drama_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    if series.kind != SeriesKind.DRAMA:
        raise ValidationFailed("该系列不是短剧制作项目。")
    return series


_VALID_GENRES = {item.value for item in SeriesGenre}
_VALID_PLATFORMS = {item.value for item in DistributionChannel}


def _clean_genre_tags(genre_tags: list[str] | None) -> list[str]:
    if not genre_tags:
        return []
    cleaned: list[str] = []
    for tag in genre_tags:
        if tag not in _VALID_GENRES:
            raise ValidationFailed(f"未知题材类型: {tag}。")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _clean_target_platforms(target_platforms: list[str] | None, *, required: bool) -> list[str]:
    if not target_platforms:
        if required:
            raise ValidationFailed("请至少选择一个发布平台。")
        return []
    cleaned: list[str] = []
    for platform in target_platforms:
        if platform not in _VALID_PLATFORMS:
            raise ValidationFailed(f"未知发布平台: {platform}。")
        if platform not in cleaned:
            cleaned.append(platform)
    return cleaned


def create_drama_series(
    session: Session,
    *,
    user_id: str,
    title: str,
    description: str | None = None,
    default_locale: str = "zh-CN",
    shortform_profile_key: str | None = None,
    allow_external_models: bool = False,
    english_title: str | None = None,
    planned_episode_count: int | None = None,
    genre_tags: list[str] | None = None,
    target_platforms: list[str] | None = None,
    logo_asset_id: str | None = None,
) -> Series:
    if logo_asset_id:
        logo = session.get(Asset, logo_asset_id)
        if logo is None or logo.owner_user_id != user_id:
            raise NotFound("logo 素材不存在。")
    series = Series(
        owner_user_id=user_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        shortform_profile_key=shortform_profile_key,
        character_ids_json=[],
        kind=SeriesKind.DRAMA,
        default_locale=default_locale,
        status=SeriesStatus.ACTIVE,
        allow_external_models=allow_external_models,
        english_title=(english_title or "").strip() or None,
        planned_episode_count=planned_episode_count,
        genre_tags_json=_clean_genre_tags(genre_tags),
        target_platforms_json=_clean_target_platforms(target_platforms, required=True),
        logo_asset_id=logo_asset_id,
    )
    session.add(series)
    session.flush()
    return series


def update_drama_series(
    session: Session,
    *,
    user_id: str,
    series_id: str,
    title: str | None = None,
    description: str | None = None,
    english_title: str | None = None,
    planned_episode_count: int | None = None,
    genre_tags: list[str] | None = None,
    target_platforms: list[str] | None = None,
    logo_asset_id: str | None = None,
) -> Series:
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    if title is not None:
        series.title = title.strip() or series.title
    if description is not None:
        series.description = description.strip() or None
    if english_title is not None:
        series.english_title = english_title.strip() or None
    if planned_episode_count is not None:
        series.planned_episode_count = planned_episode_count
    if genre_tags is not None:
        series.genre_tags_json = _clean_genre_tags(genre_tags)
    if target_platforms is not None:
        series.target_platforms_json = _clean_target_platforms(target_platforms, required=True)
    if logo_asset_id is not None:
        if logo_asset_id:
            logo = session.get(Asset, logo_asset_id)
            if logo is None or logo.owner_user_id != user_id:
                raise NotFound("logo 素材不存在。")
        series.logo_asset_id = logo_asset_id or None
    session.flush()
    return series


def trash_drama_series(session: Session, *, user_id: str, series_id: str) -> Series:
    """Moves a `kind=drama` series into the owner's recycle bin. Reversible,
    and deliberately does not check for existing episodes — trashing only
    hides the series from the default dashboard list; the episodes underneath
    still exist and are still reachable/deletable from the (still-visible)
    series-detail page. That episode-emptiness check belongs to
    `purge_drama_series`, which is the actual hard delete."""
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    if series.status == SeriesStatus.TRASHED:
        raise Conflict("剧集已在回收站中。")
    series.status = SeriesStatus.TRASHED
    series.trashed_at = utcnow()
    session.flush()
    return series


def untrash_drama_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    if series.status != SeriesStatus.TRASHED:
        raise Conflict("只有回收站中的剧集可以恢复。")
    series.status = SeriesStatus.ACTIVE
    series.trashed_at = None
    session.flush()
    return series


def purge_drama_series(session: Session, *, user_id: str, series_id: str) -> None:
    """Permanently deletes a trashed series. Blocked while it still has any
    episodes — `DramaEpisode.series_id` is `ondelete=RESTRICT`, so this check
    is enforcing at the domain layer, with a clear message, what the database
    would otherwise reject with an opaque IntegrityError."""
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    if series.status != SeriesStatus.TRASHED:
        raise Conflict("只有回收站中的剧集可以彻底删除。")
    episode_count = session.scalar(
        select(func.count()).select_from(DramaEpisode).where(DramaEpisode.series_id == series.id)
    )
    if episode_count:
        raise ValidationFailed("该剧集下还有分集，请先删除全部分集后再彻底删除。")
    session.delete(series)
    session.flush()


def list_drama_series(
    session: Session,
    *,
    user_id: str,
    q: str | None = None,
    genre: str | None = None,
    sort: str = "updated_at",
    sort_dir: str = "desc",
    status: str | None = None,
) -> list[Series]:
    stmt = select(Series).where(Series.owner_user_id == user_id, Series.kind == SeriesKind.DRAMA)
    if status == SeriesStatus.TRASHED:
        stmt = stmt.where(Series.status == SeriesStatus.TRASHED)
    else:
        stmt = stmt.where(Series.status != SeriesStatus.TRASHED)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Series.title.ilike(needle), Series.english_title.ilike(needle))
        )
    if genre:
        if genre not in _VALID_GENRES:
            raise ValidationFailed(f"未知题材类型: {genre}。")
        stmt = stmt.where(Series.genre_tags_json.contains([genre]))
    if sort_dir not in ("asc", "desc"):
        raise ValidationFailed(f"未知排序方向: {sort_dir}。")
    column = Series.created_at if sort == "created_at" else Series.updated_at
    stmt = stmt.order_by(column.asc() if sort_dir == "asc" else column.desc())
    return list(session.scalars(stmt))


def series_stats(session: Session, *, series_ids: list[str]) -> dict[str, dict[str, int]]:
    """Aggregate `关联文案数`/`关联视频数`/`已发布数` per series for the
    library card list. Computed in Python rather than raw SQL aggregates —
    a creator's own series/episode/content-link counts are small, and the
    join across `draft.published_work_id` / `episode.canonical_work_id` /
    `Work.is_publicly_visible` isn't expressible as a single clean
    aggregate anyway."""
    stats = {
        sid: {"episode_count": 0, "script_count": 0, "video_count": 0, "published_count": 0}
        for sid in series_ids
    }
    if not series_ids:
        return stats
    episodes = list(
        session.scalars(select(DramaEpisode).where(DramaEpisode.series_id.in_(series_ids)))
    )
    episode_to_series: dict[str, str] = {}
    for ep in episodes:
        bucket = stats[ep.series_id]
        bucket["episode_count"] += 1
        if ep.script_json:
            bucket["script_count"] += 1
        episode_to_series[ep.id] = ep.series_id

    if not episode_to_series:
        return stats

    links = list(
        session.scalars(
            select(EpisodeContentLink).where(
                EpisodeContentLink.episode_id.in_(episode_to_series.keys()),
                EpisodeContentLink.content_type.in_(
                    [EpisodeContentType.DRAFT, EpisodeContentType.WORK]
                ),
            )
        )
    )
    video_refs: dict[str, set[str]] = {sid: set() for sid in series_ids}
    draft_ids: set[str] = set()
    work_ids: set[str] = set()
    for link in links:
        sid = episode_to_series.get(link.episode_id)
        if sid is None:
            continue
        video_refs[sid].add(f"{link.content_type}:{link.content_ref_id}")
        if link.content_type == EpisodeContentType.DRAFT:
            draft_ids.add(link.content_ref_id)
        else:
            work_ids.add(link.content_ref_id)
    for sid, refs in video_refs.items():
        stats[sid]["video_count"] = len(refs)

    canonical_ids = {ep.canonical_work_id for ep in episodes if ep.canonical_work_id}
    work_ids |= canonical_ids
    drafts_by_id = (
        {d.id: d for d in session.scalars(select(Draft).where(Draft.id.in_(draft_ids)))}
        if draft_ids
        else {}
    )
    work_ids |= {d.published_work_id for d in drafts_by_id.values() if d.published_work_id}
    works_by_id = (
        {w.id: w for w in session.scalars(select(Work).where(Work.id.in_(work_ids)))}
        if work_ids
        else {}
    )

    published_by_series: dict[str, set[str]] = {sid: set() for sid in series_ids}
    for link in links:
        sid = episode_to_series.get(link.episode_id)
        if sid is None:
            continue
        target_work_id = None
        if link.content_type == EpisodeContentType.WORK:
            target_work_id = link.content_ref_id
        elif link.content_type == EpisodeContentType.DRAFT:
            draft = drafts_by_id.get(link.content_ref_id)
            target_work_id = draft.published_work_id if draft else None
        work = works_by_id.get(target_work_id) if target_work_id else None
        if work is not None and work.is_publicly_visible:
            published_by_series[sid].add(work.id)
    for ep in episodes:
        if not ep.canonical_work_id:
            continue
        work = works_by_id.get(ep.canonical_work_id)
        if work is not None and work.is_publicly_visible:
            published_by_series[ep.series_id].add(work.id)
    for sid, ids in published_by_series.items():
        stats[sid]["published_count"] = len(ids)

    return stats


def episodes_with_script_turns(session: Session, *, episode_ids: list[str]) -> set[str]:
    """Which of `episode_ids` have at least one `EpisodeScriptTurn`.

    Batched (one `IN` query for the whole list/detail response) rather than
    one `EXISTS` per episode — see `api.v1.editor.episode_response`'s
    `has_script_turns`, which flags a script-writing shell whose first
    draft is still streaming elsewhere or failed outright (mirrors
    `script_writing_service.list_scripts`'s own relaxed, turn-agnostic
    filter).
    """
    if not episode_ids:
        return set()
    return set(
        session.scalars(
            select(EpisodeScriptTurn.episode_id)
            .where(EpisodeScriptTurn.episode_id.in_(episode_ids))
            .distinct()
        )
    )


def create_episode(
    session: Session,
    *,
    user_id: str,
    series_id: str,
    title: str,
    episode_number: int | None = None,
    season_number: int = 1,
    episode_kind: str = EpisodeKind.MAIN,
    synopsis: str | None = None,
) -> DramaEpisode:
    """Basic episode CRUD is intentionally *not* flag-gated and not limited
    to `kind=drama` series — every series (the roster's `kind=cast` short-
    drama entries included) can manage its own episode list. Only entering
    the full timeline editor (`create_cut_from_job`/`acquire_lease`/
    `apply_commands`/exports/AI) still requires `FLAG_EDITOR` and friends —
    see `zaolang-editor-drama`."""
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    number = episode_number
    if number is None:
        current = session.scalars(
            select(DramaEpisode.episode_number)
            .where(
                DramaEpisode.series_id == series.id,
                DramaEpisode.season_number == season_number,
            )
            .order_by(DramaEpisode.episode_number.desc())
        ).first()
        number = int(current or 0) + 1
    existing = session.scalar(
        select(DramaEpisode).where(
            DramaEpisode.series_id == series.id,
            DramaEpisode.season_number == season_number,
            DramaEpisode.episode_number == number,
        )
    )
    if existing is not None:
        raise ValidationFailed("该集数已存在。")
    episode = DramaEpisode(
        series_id=series.id,
        season_number=season_number,
        episode_number=number,
        episode_kind=episode_kind,
        title=title.strip(),
        synopsis=(synopsis or "").strip() or None,
        script_json={},
        status=DramaEpisodeStatus.DRAFT,
    )
    session.add(episode)
    session.flush()
    return episode


def list_episodes(session: Session, *, user_id: str, series_id: str) -> list[DramaEpisode]:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    stmt = (
        select(DramaEpisode)
        .where(DramaEpisode.series_id == series.id)
        .order_by(DramaEpisode.season_number.asc(), DramaEpisode.episode_number.asc())
    )
    return list(session.scalars(stmt))


def get_episode(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    return _owned_episode(session, user_id=user_id, episode_id=episode_id)


def update_episode(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    title: str | None = None,
    synopsis: str | None = None,
    episode_kind: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
    status: str | None = None,
) -> DramaEpisode:
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    next_season = season_number if season_number is not None else episode.season_number
    next_number = episode_number if episode_number is not None else episode.episode_number
    if next_season != episode.season_number or next_number != episode.episode_number:
        clash = session.scalar(
            select(DramaEpisode).where(
                DramaEpisode.series_id == episode.series_id,
                DramaEpisode.season_number == next_season,
                DramaEpisode.episode_number == next_number,
                DramaEpisode.id != episode.id,
            )
        )
        if clash is not None:
            raise ValidationFailed("该集数已存在。")
        episode.season_number = next_season
        episode.episode_number = next_number
    if title is not None:
        episode.title = title.strip() or episode.title
    if synopsis is not None:
        episode.synopsis = synopsis.strip() or None
    if episode_kind is not None:
        episode.episode_kind = episode_kind
    if status is not None:
        episode.status = status
    session.flush()
    return episode


def delete_episode(session: Session, *, user_id: str, episode_id: str) -> None:
    """Hard-deletes an episode. Blocked while it has any `EpisodeCut` rows
    (`ondelete=RESTRICT`) — there is no way to delete a cut in this codebase
    today (a cut gets a revision immediately on creation, and revisions are
    themselves RESTRICT-linked), so an episode that has entered the timeline
    editor cannot be deleted at all, not even after removing its cuts one by
    one. `EpisodeContentLink`/`EpisodeScriptTurn` are `ondelete=CASCADE` and
    need no precheck. This intentionally runs its own unflagged count query
    rather than reusing `list_cuts`, which gates on `FLAG_EDITOR` — basic
    episode CRUD is not flag-gated (see `create_episode`'s docstring)."""
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    cut_count = session.scalar(
        select(func.count()).select_from(EpisodeCut).where(EpisodeCut.episode_id == episode.id)
    )
    if cut_count:
        raise ValidationFailed("该集已进入剪辑，暂不支持删除。")
    session.delete(episode)
    session.flush()


def _content_owner_user_id(
    session: Session, *, content_type: str, content_ref_id: str
) -> str | None:
    """Traces a piece of content back to whoever owns it, for the ownership
    check `create_content_link` needs before letting a user attach it to
    their episode. Not a foreign key (see `EpisodeContentLink`'s docstring),
    so this has to walk each content type's own path by hand."""
    if content_type == EpisodeContentType.DRAFT:
        draft = session.get(Draft, content_ref_id)
        return draft.user_id if draft else None
    if content_type == EpisodeContentType.WORK:
        work = session.get(Work, content_ref_id)
        return work.owner_user_id if work else None
    if content_type == EpisodeContentType.EDITOR_EXPORT:
        export = session.get(EditorExport, content_ref_id)
        if export is None:
            return None
        variant = session.get(DeliveryVariant, export.variant_id)
        revision = session.get(CutRevision, variant.cut_revision_id) if variant else None
        cut = session.get(EpisodeCut, revision.cut_id) if revision else None
        episode = session.get(DramaEpisode, cut.episode_id) if cut else None
        series = session.get(Series, episode.series_id) if episode else None
        return series.owner_user_id if series else None
    return None


def create_content_link(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    content_type: str,
    content_ref_id: str,
    role: str = EpisodeContentRole.CANDIDATE,
) -> EpisodeContentLink:
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    owner_id = _content_owner_user_id(
        session, content_type=content_type, content_ref_id=content_ref_id
    )
    if owner_id is None:
        raise NotFound("关联的内容不存在。")
    if owner_id != user_id:
        raise Forbidden("不能关联他人的创作产出。")
    existing = session.scalar(
        select(EpisodeContentLink).where(
            EpisodeContentLink.episode_id == episode.id,
            EpisodeContentLink.content_type == content_type,
            EpisodeContentLink.content_ref_id == content_ref_id,
        )
    )
    if existing is not None:
        if existing.role != role:
            existing.role = role
            session.flush()
        return existing
    link = EpisodeContentLink(
        episode_id=episode.id,
        content_type=content_type,
        content_ref_id=content_ref_id,
        role=role,
    )
    session.add(link)
    session.flush()
    return link


def maybe_link_draft(
    session: Session, *, user_id: str, episode_id: str, draft_id: str
) -> EpisodeContentLink | None:
    """Attach a draft as a `candidate` when the caller owns both. Foreign
    or missing episodes raise so `create_draft` can swallow them without
    rolling the draft back."""
    try:
        return create_content_link(
            session,
            user_id=user_id,
            episode_id=episode_id,
            content_type=EpisodeContentType.DRAFT,
            content_ref_id=draft_id,
            role=EpisodeContentRole.CANDIDATE,
        )
    except (NotFound, Forbidden):
        return None


def ensure_linked_drafts(session: Session, *, user_id: str, episode_id: str) -> None:
    """Heal drafts that already carry `params.link_episode_id` but never got
    a content-link row (the write path used to persist the param only)."""
    drafts = session.scalars(
        select(Draft).where(
            Draft.user_id == user_id,
            Draft.params_json.contains({"link_episode_id": episode_id}),
        )
    )
    for draft in drafts:
        maybe_link_draft(
            session, user_id=user_id, episode_id=episode_id, draft_id=draft.id
        )


def list_content_links(
    session: Session, *, user_id: str, episode_id: str
) -> list[EpisodeContentLink]:
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    ensure_linked_drafts(session, user_id=user_id, episode_id=episode.id)
    stmt = (
        select(EpisodeContentLink)
        .where(EpisodeContentLink.episode_id == episode.id)
        .order_by(EpisodeContentLink.created_at.desc())
    )
    return list(session.scalars(stmt))


def delete_content_link(session: Session, *, user_id: str, episode_id: str, link_id: str) -> None:
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    link = session.get(EpisodeContentLink, link_id)
    if link is None or link.episode_id != episode.id:
        raise NotFound("关联记录不存在。")
    session.delete(link)
    session.flush()


def set_canonical_work(
    session: Session, *, user_id: str, episode_id: str, work_id: str | None
) -> DramaEpisode:
    """Names the one output the episode's publishing flow (`PublishKit`) and
    the public projection should trust as current — see
    `EpisodeContentRole`'s docstring for why this is a dedicated column
    rather than just "the link with role=final"."""
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    if work_id is not None:
        work = session.get(Work, work_id)
        if work is None or work.owner_user_id != user_id:
            raise NotFound("作品不存在。")
        create_content_link(
            session,
            user_id=user_id,
            episode_id=episode_id,
            content_type=EpisodeContentType.WORK,
            content_ref_id=work_id,
            role=EpisodeContentRole.FINAL,
        )
    episode.canonical_work_id = work_id
    session.flush()
    return episode


def list_cuts(session: Session, *, user_id: str, episode_id: str) -> list[EpisodeCut]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    stmt = (
        select(EpisodeCut)
        .where(EpisodeCut.episode_id == episode.id)
        .order_by(EpisodeCut.created_at.desc())
    )
    return list(session.scalars(stmt))


def _linked_episode_id_from_job(session: Session, job: GenerationJob) -> str | None:
    """The script-studio jump-out writes `params.link_episode_id` on the
    draft. A missing draft, or a missing/non-string value, means this job
    is not that path — the caller may fall back to minting a shell.
    A *present* id is never treated as absent: resolving it is the
    caller's job, including the 4xx when the episode is gone or foreign.
    """
    if not job.draft_id:
        return None
    draft = session.get(Draft, job.draft_id)
    if draft is None:
        return None
    episode_id = (draft.params_json or {}).get("link_episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        return None
    return episode_id


def create_cut_from_job(
    session: Session,
    *,
    user_id: str,
    job_id: str,
    series_id: str | None = None,
    title: str | None = None,
) -> tuple[EpisodeCut, CutRevision]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    job = session.get(GenerationJob, job_id)
    if job is None or job.user_id != user_id:
        raise NotFound("生成任务不存在。")
    if job.status != JobStatus.SUCCEEDED or not job.output_asset_id:
        raise ValidationFailed("只有成功且带成片的任务才能进入剪辑。")
    # A script-studio video jump-out already named the episode. Reuse it —
    # never mint a second series/episode, even if `series_id` was also sent.
    # A present-but-foreign/missing id must 4xx rather than fall through to
    # the shell-creating fallback below.
    linked_episode_id = _linked_episode_id_from_job(session, job)
    if linked_episode_id is not None:
        episode = _owned_episode(session, user_id=user_id, episode_id=linked_episode_id)
        return create_cut_from_asset(
            session,
            user_id=user_id,
            episode_id=episode.id,
            asset_id=job.output_asset_id,
            job_id=job.id,
        )
    if series_id:
        series = require_drama_series(session, user_id=user_id, series_id=series_id)
    else:
        existing = session.scalars(
            select(Series)
            .where(
                Series.owner_user_id == user_id,
                Series.kind == SeriesKind.DRAMA,
                Series.status != SeriesStatus.TRASHED,
            )
            .order_by(Series.created_at.desc())
        ).first()
        # Auto-created fallback series (user jumped straight from a generation
        # job into "进入剪辑" without going through the series library's
        # create dialog, and the draft carried no `link_episode_id`) —
        # `target_platforms` defaults to manual download only, editable later
        # via `PATCH /v1/drama-series/{id}`.
        series = existing or create_drama_series(
            session,
            user_id=user_id,
            title=(title or "短剧").strip() or "短剧",
            target_platforms=[DistributionChannel.MANUAL_DOWNLOAD.value],
        )
    episode = create_episode(
        session,
        user_id=user_id,
        series_id=series.id,
        title=(title or "新一集").strip() or "新一集",
    )
    return create_cut_from_asset(
        session,
        user_id=user_id,
        episode_id=episode.id,
        asset_id=job.output_asset_id,
        job_id=job.id,
    )


def create_cut_from_asset(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    asset_id: str,
    name: str = "主剪辑",
    kind: str = EpisodeCutKind.FULL,
    job_id: str | None = None,
) -> tuple[EpisodeCut, CutRevision]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != user_id:
        raise Forbidden("不能使用他人的素材作为剪辑源。")
    if job_id:
        job = session.get(GenerationJob, job_id)
        if job is None or job.user_id != user_id or job.output_asset_id != asset_id:
            raise ValidationFailed("生成任务与素材不匹配。")
    cut = EpisodeCut(
        episode_id=episode.id,
        kind=kind,
        name=name.strip() or "主剪辑",
        status=EpisodeCutStatus.DRAFT,
        source_asset_id=asset.id,
        source_job_id=job_id,
    )
    session.add(cut)
    session.flush()
    duration = ticks_from_ms(asset.duration_ms)
    canvas_w = asset.width or 1080
    canvas_h = asset.height or 1920
    document = docs.empty_document(width=canvas_w, height=canvas_h)
    batch = {
        "schema_version": 1,
        "batch_id": new_id("bat"),
        "expected_revision_id": None,
        "commands": [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": asset.id,
                "at_ticks": 0,
                "duration_ticks": duration,
                "source_in_ticks": 0,
            }
        ],
    }
    validated = command_codec.validate_batch(batch)
    applied = command_codec.apply_batch(document, validated["commands"], known_assets={asset.id})
    bindings = [{"asset_id": asset.id, "role": "source", "duration_ticks": duration}]
    revision = _persist_revision(
        session,
        cut=cut,
        parent=None,
        document=applied,
        bindings=bindings,
        user_id=user_id,
        command_summary={"source": "create_cut", "commands": validated["commands"]},
    )
    cut.head_revision_id = revision.id
    cut.status = EpisodeCutStatus.EDITING
    session.flush()
    return cut, revision


def acquire_lease(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    browser_instance_id: str,
) -> tuple[EditorLease, str]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    return lease_service.acquire(
        session, cut=cut, user_id=user_id, browser_instance_id=browser_instance_id
    )


def apply_commands(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    lease_id: str,
    lease_token: str,
    payload: dict[str, Any],
) -> CutRevision:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    # Locks the cut row for the rest of this transaction so two concurrent
    # writers computing the same next revision_no can't both pass the CAS
    # check in Python; the loser blocks here instead of racing the unique
    # constraint on cut_revisions(cut_id, revision_no).
    #
    # `populate_existing=True` is required here: `_owned_cut` above already
    # loaded `cut` into the session's identity map with an *unlocked* read.
    # Without it, `Session.get(..., with_for_update=True)` still emits the
    # locking SELECT (and correctly blocks until any concurrent writer
    # commits), but SQLAlchemy silently keeps the *stale* in-memory
    # attributes from that first read instead of refreshing them from the
    # just-fetched row — so `cut.head_revision_id` below can stay pinned to
    # the pre-lock value forever, even though the lock itself was acquired
    # against the live, current row. That made every command after a
    # concurrent writer's commit fail the CAS check (or race the
    # `revision_no` unique constraint into a 409) even when the caller's
    # `expected_revision_id` was actually correct.
    cut = session.get(EpisodeCut, cut.id, with_for_update=True, populate_existing=True) or cut
    lease = lease_service.require_write_lease(
        session, cut_id=cut.id, user_id=user_id, lease_id=lease_id, token=lease_token
    )
    batch = command_codec.validate_batch(
        {
            "schema_version": payload.get("schema_version"),
            "batch_id": payload.get("batch_id"),
            "expected_revision_id": payload.get("expected_revision_id"),
            "commands": payload.get("commands"),
        }
    )
    head = session.get(CutRevision, cut.head_revision_id) if cut.head_revision_id else None
    expected = batch["expected_revision_id"]
    if expected != (head.id if head else None):
        raise RevisionConflict()
    document = docs.clone_document(head.document_json) if head else docs.empty_document()
    known = {str(item.get("asset_id")) for item in (head.asset_bindings_json if head else [])}
    known |= {
        str(command.get("asset_id")) for command in batch["commands"] if command.get("asset_id")
    }
    _assert_assets_owned(session, user_id=user_id, asset_ids=known)
    applied = command_codec.apply_batch(document, batch["commands"], known_assets=known)
    bindings = _bindings_from_document(applied)
    try:
        revision = _persist_revision(
            session,
            cut=cut,
            parent=head,
            document=applied,
            bindings=bindings,
            user_id=user_id,
            command_summary={"batch_id": batch["batch_id"], "commands": batch["commands"]},
        )
    except IntegrityError as error:
        session.rollback()
        raise RevisionConflict() from error
    if cut.head_revision_id != (head.id if head else None):
        raise RevisionConflict()
    cut.head_revision_id = revision.id
    lease.last_sequence += 1
    lease.base_revision_id = revision.id
    event = EditorCommandEvent(
        lease_id=lease.id,
        sequence=lease.last_sequence,
        batch_id=batch["batch_id"],
        expected_revision_id=expected,
        result_revision_id=revision.id,
        commands_json=batch["commands"],
        status=EditorCommandEventStatus.APPLIED,
        created_at=utcnow(),
    )
    session.add(event)
    session.flush()
    return revision


def head_revision(session: Session, cut: EpisodeCut) -> CutRevision | None:
    if not cut.head_revision_id:
        return None
    return session.get(CutRevision, cut.head_revision_id)


def list_revisions(session: Session, *, user_id: str, cut_id: str) -> list[CutRevision]:
    """Newest-first revision history for the editor's own history panel —
    this is the only place a past `CutRevision` becomes browsable; the
    episode page no longer lists cuts at all (see `zaolang-editor-drama`)."""
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    stmt = (
        select(CutRevision)
        .where(CutRevision.cut_id == cut.id)
        .order_by(CutRevision.revision_no.desc())
    )
    return list(session.scalars(stmt))


def restore_revision(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    revision_id: str,
    expected_revision_id: str | None,
    lease_id: str,
    lease_token: str,
) -> CutRevision:
    """Rolls the timeline back to an earlier revision's content by writing
    a brand-new head revision that copies it — history itself is never
    rewritten (immutable snapshots, invariant #2), so "restore" is just
    another editing action gated by the exact same lease + CAS check as
    `apply_commands`, not a special-cased mutation."""
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    # See the matching comment in `apply_commands`: `populate_existing=True`
    # forces this locking re-fetch to actually refresh `cut`'s attributes
    # (notably `head_revision_id`) instead of keeping the stale values from
    # `_owned_cut`'s earlier unlocked read.
    cut = session.get(EpisodeCut, cut.id, with_for_update=True, populate_existing=True) or cut
    lease = lease_service.require_write_lease(
        session, cut_id=cut.id, user_id=user_id, lease_id=lease_id, token=lease_token
    )
    target = session.get(CutRevision, revision_id)
    if target is None or target.cut_id != cut.id:
        raise NotFound("历史版本不存在。")
    head = session.get(CutRevision, cut.head_revision_id) if cut.head_revision_id else None
    if expected_revision_id != (head.id if head else None):
        raise RevisionConflict()
    if head is not None and target.id == head.id:
        return head
    document = docs.clone_document(target.document_json)
    bindings = list(target.asset_bindings_json)
    try:
        revision = _persist_revision(
            session,
            cut=cut,
            parent=head,
            document=document,
            bindings=bindings,
            user_id=user_id,
            command_summary={"source": "restore_revision", "restored_from": target.id},
        )
    except IntegrityError as error:
        session.rollback()
        raise RevisionConflict() from error
    if cut.head_revision_id != (head.id if head else None):
        raise RevisionConflict()
    cut.head_revision_id = revision.id
    lease.last_sequence += 1
    lease.base_revision_id = revision.id
    event = EditorCommandEvent(
        lease_id=lease.id,
        sequence=lease.last_sequence,
        batch_id=new_id("bat"),
        expected_revision_id=expected_revision_id,
        result_revision_id=revision.id,
        commands_json=[{"type": "restore_revision", "revision_id": target.id}],
        status=EditorCommandEventStatus.APPLIED,
        created_at=utcnow(),
    )
    session.add(event)
    session.flush()
    return revision


def create_variants(
    session: Session,
    *,
    user_id: str,
    revision_id: str,
    profile_keys: list[str],
    caption_language: str | None = None,
    caption_mode: str = "burned",
    format: str = "mp4",
) -> list[DeliveryVariant]:
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    revision = session.get(CutRevision, revision_id)
    if revision is None:
        raise NotFound("修订不存在。")
    cut = _owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
    del cut
    cfg = config_service.get_typed(session, "shortform", ShortformConfig)
    created: list[DeliveryVariant] = []
    for key in profile_keys:
        profile = cfg.profiles.get(key)
        if profile is None:
            raise ValidationFailed(f"未知交付规格: {key}。")
        spec = {
            "profile_key": key,
            "aspect_ratio": profile.aspect_ratio,
            "width": profile.width,
            "height": profile.height,
            "fps_num": 30,
            "fps_den": 1,
            "format": format,
            "caption_language": caption_language,
            "caption_mode": caption_mode,
            "max_duration_ticks": profile.max_duration_seconds * 120_000,
        }
        digest = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = session.scalar(
            select(DeliveryVariant).where(
                DeliveryVariant.cut_revision_id == revision.id,
                DeliveryVariant.spec_hash == digest,
            )
        )
        if existing is not None:
            created.append(existing)
            continue
        variant = DeliveryVariant(
            cut_revision_id=revision.id,
            profile_key=key,
            aspect_ratio=profile.aspect_ratio,
            width=profile.width,
            height=profile.height,
            fps_num=30,
            fps_den=1,
            format=format,
            caption_language=caption_language,
            caption_mode=caption_mode,
            spec_json=spec,
            spec_hash=digest,
            status=DeliveryVariantStatus.READY,
        )
        session.add(variant)
        session.flush()
        created.append(variant)
    return created


def append_operation_event(
    session: Session,
    operation_id: str,
    *,
    event_type: str,
    status: str,
    public_message: str,
    progress: int = 0,
    payload: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> EditorOperationEvent:
    current_max = session.scalar(
        select(EditorOperationEvent.sequence)
        .where(EditorOperationEvent.operation_id == operation_id)
        .order_by(EditorOperationEvent.sequence.desc())
        .limit(1)
    )
    event = EditorOperationEvent(
        operation_id=operation_id,
        sequence=(current_max or 0) + 1,
        event_type=event_type,
        status=status,
        progress=max(0, min(100, progress)),
        public_message=public_message,
        payload_json=payload or {},
        created_at=now or utcnow(),
    )
    session.add(event)
    session.flush()
    publisher.publish_job_event(
        operation_id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        },
    )
    return event


def events_since(session: Session, operation_id: str, after: int) -> list[EditorOperationEvent]:
    stmt = (
        select(EditorOperationEvent)
        .where(
            EditorOperationEvent.operation_id == operation_id,
            EditorOperationEvent.sequence > after,
        )
        .order_by(EditorOperationEvent.sequence.asc())
    )
    return list(session.scalars(stmt))


def create_edit_plan(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    goal: str,
    commands: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    agent_run_id: str | None = None,
    model: str | None = None,
    warnings: list[str] | None = None,
) -> EditPlan:
    editor_flags.require_flag(session, editor_flags.FLAG_AI, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    head = head_revision(session, cut)
    if head is None:
        raise ValidationFailed("剪辑还没有可编辑的修订。")
    plan = EditPlan(
        cut_id=cut.id,
        base_revision_id=head.id,
        status=EditPlanStatus.VALIDATED,
        summary=summary or goal.strip()[:240],
        commands_json=commands or [],
        warnings_json=warnings or [],
        agent_run_id=agent_run_id,
        model=model,
        prompt_slot="timeline_edit_plan",
        expires_at=utcnow() + dt.timedelta(hours=6),
        created_by_user_id=user_id,
    )
    if commands:
        try:
            validated = command_codec.validate_batch(
                {
                    "schema_version": 1,
                    "batch_id": new_id("bat"),
                    "expected_revision_id": head.id,
                    "commands": commands,
                }
            )
            preview = command_codec.apply_batch(
                docs.clone_document(head.document_json),
                validated["commands"],
                known_assets={str(item.get("asset_id")) for item in head.asset_bindings_json},
            )
            plan.commands_json = validated["commands"]
            plan.diff_json = {
                "base_duration_ticks": head.duration_ticks,
                "result_duration_ticks": docs.duration_ticks(preview),
            }
            plan.validation_json = {"ok": True}
        except Exception as exc:
            plan.status = EditPlanStatus.FAILED
            plan.validation_json = {"ok": False, "error": str(exc)}
    else:
        plan.validation_json = {"ok": True, "empty": True}
    session.add(plan)
    session.flush()
    return plan


def apply_edit_plan(
    session: Session,
    *,
    user_id: str,
    plan_id: str,
    lease_id: str,
    lease_token: str,
    selected_indexes: list[int] | None = None,
) -> CutRevision:
    plan = session.get(EditPlan, plan_id)
    if plan is None:
        raise NotFound("剪辑方案不存在。")
    commands = list(plan.commands_json)
    if selected_indexes is not None:
        commands = [commands[i] for i in selected_indexes if 0 <= i < len(commands)]
    revision = apply_commands(
        session,
        user_id=user_id,
        cut_id=plan.cut_id,
        lease_id=lease_id,
        lease_token=lease_token,
        payload={
            "schema_version": 1,
            "batch_id": new_id("bat"),
            "expected_revision_id": plan.base_revision_id,
            "commands": commands,
        },
    )
    state_machine.transition_plan(session, plan.id, EditPlanStatus.APPLIED)
    plan.applied_revision_id = revision.id
    session.flush()
    return revision


def reject_edit_plan(session: Session, *, user_id: str, plan_id: str) -> EditPlan:
    plan = session.get(EditPlan, plan_id)
    if plan is None:
        raise NotFound("剪辑方案不存在。")
    _owned_cut(session, user_id=user_id, cut_id=plan.cut_id)
    return state_machine.transition_plan(session, plan.id, EditPlanStatus.REJECTED)


def _persist_revision(
    session: Session,
    *,
    cut: EpisodeCut,
    parent: CutRevision | None,
    document: dict[str, Any],
    bindings: list[dict[str, Any]],
    user_id: str,
    command_summary: dict[str, Any],
) -> CutRevision:
    digest = docs.content_hash(document, bindings)
    existing = session.scalar(
        select(CutRevision).where(CutRevision.cut_id == cut.id, CutRevision.content_hash == digest)
    )
    if existing is not None:
        return existing
    # Deliberately *not* `(parent.revision_no + 1)`: undo/redo (`restore_revision`)
    # can move `head` back to an old revision and then have a genuinely new
    # edit applied on top of it. That new edit's parent has a lower
    # `revision_no` than revisions that already exist later in a since-
    # abandoned branch, so `parent.revision_no + 1` can collide with one of
    # those and trip the `uq_cut_revisions_cut_revision` unique constraint —
    # surfacing to the client as a bogus `REVISION_CONFLICT` even though
    # nobody else touched the cut. `revision_no` only needs to be unique per
    # cut and roughly monotonic for display purposes, not a strict
    # `parent + 1` counter, so basing it on the cut's current max is safe and
    # collision-free across branches.
    current_max = session.scalar(
        select(func.max(CutRevision.revision_no)).where(CutRevision.cut_id == cut.id)
    )
    revision_no = (current_max or 0) + 1
    revision = CutRevision(
        cut_id=cut.id,
        revision_no=revision_no,
        parent_revision_id=parent.id if parent else None,
        engine="zaolang-canonical",
        engine_schema_version=1,
        document_json=docs.canonicalize(document),
        asset_bindings_json=bindings,
        duration_ticks=docs.duration_ticks(document),
        content_hash=digest,
        command_summary_json=command_summary,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )
    session.add(revision)
    session.flush()
    return revision


def _bindings_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in docs.iter_elements(document):
        asset_id = element.get("asset_id")
        if not asset_id or asset_id in seen:
            continue
        seen.add(str(asset_id))
        bindings.append(
            {
                "asset_id": asset_id,
                "role": "source" if element.get("type") == "clip" else "caption",
                "duration_ticks": element.get("duration_ticks"),
            }
        )
    overlay = document.get("brand_overlay") or {}
    if overlay.get("asset_id"):
        bindings.append({"asset_id": overlay["asset_id"], "role": "brand", "duration_ticks": None})
    return bindings


def _assert_assets_owned(session: Session, *, user_id: str, asset_ids: set[str]) -> None:
    ids = [asset_id for asset_id in asset_ids if asset_id]
    if not ids:
        return
    rows = list(session.scalars(select(Asset).where(Asset.id.in_(ids))))
    owned = {row.id for row in rows if row.owner_user_id == user_id}
    missing = set(ids) - owned
    if missing:
        raise Forbidden("命令引用了无权使用的素材。")
