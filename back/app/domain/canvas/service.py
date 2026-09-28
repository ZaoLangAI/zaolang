"""Canvas projects — project CRUD, access, and the one batched hydration read.

The graph itself (cards, connections, the change feed) lives in
`graph_service`; this module owns the project row and who may touch it.

Two rules shape everything here:

* **The canvas never becomes a second write path for domain objects.** Cards
  carry a `binding` pointing at a `DramaEpisode` / breakpoint /
  `CreationSkill` / `Draft` / `Work`, but creating, editing and deleting those
  objects keeps going through their own routes. What the canvas does own is
  its own content — including cards an Agent generated — which is a different
  thing from owning the domain.
* **Access follows the mode.** A drama-mode canvas is a *management*
  surface, so `editor_service._accessible_series` applies (owner or active
  co-creator, matching episode/script/content-link CRUD). A free canvas has
  no series to derive that from and is strictly its owner's.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.canvas import graph_service
from app.domain.editor import service as editor_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import (
    Asset,
    CanvasProject,
    CreationSkill,
    Draft,
    DramaEpisode,
    EpisodeContentLink,
    Series,
    SeriesCollaborator,
    Work,
    WorkVersion,
)
from app.models.enums import (
    CreationSkillStatus,
    EpisodeContentType,
    SeriesCollaboratorStatus,
)
from app.platform_config import service as config_service
from app.presenters import media_urls

CANVAS_STUDIO_FLAG = "canvas_studio_enabled"

MAX_TITLE_LEN = 200


def _require_flag(session: Session, *, user_id: str | None) -> None:
    if not config_service.is_enabled(session, CANVAS_STUDIO_FLAG, user_id=user_id):
        raise NotFound("该功能暂未开放。")


def _accessible_project(session: Session, *, user_id: str, canvas_id: str) -> CanvasProject:
    """Owner always; for a drama-mode canvas, an active co-creator too.

    Mirrors `_accessible_series`'s "invisible rather than forbidden" choice —
    a canvas the caller may not see 404s rather than 403s, so its existence
    is not confirmed.
    """
    project = session.get(CanvasProject, canvas_id)
    if project is None:
        raise NotFound("画布不存在。")
    if project.owner_user_id == user_id:
        return project
    if project.series_id is None:
        # A free canvas has no collaborator concept at all.
        raise NotFound("画布不存在。")
    # Raises NotFound itself when the caller is neither owner nor co-creator.
    editor_service._accessible_series(session, user_id=user_id, series_id=project.series_id)
    return project


def create_project(
    session: Session,
    *,
    user_id: str,
    title: str,
    series_id: str | None = None,
) -> CanvasProject:
    _require_flag(session, user_id=user_id)
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationFailed("请填写画布名称。")
    if len(clean_title) > MAX_TITLE_LEN:
        raise ValidationFailed(f"画布名称不能超过 {MAX_TITLE_LEN} 个字符。")
    if series_id is not None:
        # Same access rule the canvas itself will use afterwards.
        editor_service._accessible_series(session, user_id=user_id, series_id=series_id)
        existing = session.scalar(select(CanvasProject).where(CanvasProject.series_id == series_id))
        if existing is not None:
            # The partial unique index would reject this anyway; saying so in
            # the domain layer keeps the caller from seeing an opaque
            # IntegrityError for what is a normal "already exists" case.
            raise ValidationFailed("该短剧已经有一个画布了。")
    project = CanvasProject(
        owner_user_id=user_id,
        series_id=series_id,
        title=clean_title,
        viewport_json={},
        change_seq=0,
        updated_by_user_id=user_id,
    )
    session.add(project)
    session.flush()
    return project


def get_or_create_for_series(session: Session, *, user_id: str, series_id: str) -> CanvasProject:
    """Backs `series-detail.tsx`'s "画布视图" button — one click, no setup."""
    _require_flag(session, user_id=user_id)
    series = editor_service._accessible_series(session, user_id=user_id, series_id=series_id)
    existing = session.scalar(select(CanvasProject).where(CanvasProject.series_id == series_id))
    if existing is not None:
        return existing
    return create_project(session, user_id=user_id, title=series.title, series_id=series_id)


def list_projects(session: Session, *, user_id: str) -> list[CanvasProject]:
    """Canvases the caller owns, plus drama canvases of series they co-create.

    A collaborator sees the shared series' canvas because they can already
    manage that series' episodes and scripts; they never see the owner's
    free canvases, which are personal.
    """
    _require_flag(session, user_id=user_id)
    owned = list(
        session.scalars(select(CanvasProject).where(CanvasProject.owner_user_id == user_id))
    )
    # Joined rather than filtered in Python: the naive version loads every
    # other user's canvases before discarding them, which is both a full
    # table scan and a per-row membership query.
    shared = list(
        session.scalars(
            select(CanvasProject)
            .join(SeriesCollaborator, SeriesCollaborator.series_id == CanvasProject.series_id)
            .where(
                CanvasProject.owner_user_id != user_id,
                SeriesCollaborator.user_id == user_id,
                SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
            )
        )
    )
    combined = owned + shared
    combined.sort(key=lambda project: project.updated_at, reverse=True)
    return combined


def get_project(session: Session, *, user_id: str, canvas_id: str) -> CanvasProject:
    _require_flag(session, user_id=user_id)
    return _accessible_project(session, user_id=user_id, canvas_id=canvas_id)


def update_project(
    session: Session,
    *,
    user_id: str,
    canvas_id: str,
    title: str | None = None,
    viewport: dict[str, Any] | None = None,
) -> CanvasProject:
    """Project metadata only — the graph is written through `graph_service`.

    Deliberately not compare-and-set. The column that used to guard this
    (`revision`) was a whole-document token two writers had to fight over, and
    it is gone; what is left here is a title and a camera position, where a
    race is worth strictly less than the 409 it would cost to prevent. The
    sequence is still bumped so a listening client learns to re-read the row.
    """
    _require_flag(session, user_id=user_id)
    project = _accessible_project(session, user_id=user_id, canvas_id=canvas_id)
    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise ValidationFailed("请填写画布名称。")
        if len(clean_title) > MAX_TITLE_LEN:
            raise ValidationFailed(f"画布名称不能超过 {MAX_TITLE_LEN} 个字符。")
        project.title = clean_title
    if viewport is not None:
        project.viewport_json = viewport
    project.updated_by_user_id = user_id
    graph_service.touch(session, canvas_id)
    session.flush()
    return project


def delete_project(session: Session, *, user_id: str, canvas_id: str) -> None:
    """Owner-only, even in drama mode — deleting the workspace is not part of
    the management grant a co-creator gets (same boundary as trash/purge)."""
    _require_flag(session, user_id=user_id)
    project = session.get(CanvasProject, canvas_id)
    if project is None or project.owner_user_id != user_id:
        raise NotFound("画布不存在。")
    session.delete(project)
    session.flush()


# --------------------------------------------------------------------------
# Hydration
# --------------------------------------------------------------------------


def _asset_owner_ids(session: Session, project: CanvasProject) -> set[str]:
    """Whose assets may render on this canvas.

    The owner, plus — on a drama canvas — every active co-creator.
    `register_generated_asset` stamps `owner_user_id = job.user_id`, so a
    co-creator's generated image belongs to *them*, not to the series owner.
    Filtering on the project owner alone (as this did originally) rendered
    every collaborator-generated card as a broken image on the shared canvas.
    """
    owners = {project.owner_user_id}
    if project.series_id is not None:
        owners.update(
            session.scalars(
                select(SeriesCollaborator.user_id).where(
                    SeriesCollaborator.series_id == project.series_id,
                    SeriesCollaborator.status == SeriesCollaboratorStatus.ACTIVE,
                )
            )
        )
    return owners


def _node_asset_urls(session: Session, project: CanvasProject) -> dict[str, Any]:
    """Signed URLs for the assets this canvas' own cards point at.

    A card stores only `binding.asset_id`, never a URL: a presigned URL
    expires, so persisting one would give a canvas that renders for an hour and
    then shows broken images forever. Ownership is re-checked here rather than
    trusted from the card — node rows are client-written, so an id pasted into
    one must not become a read primitive for someone else's private object.
    """
    wanted = graph_service.bound_asset_ids(session, project.id)
    if not wanted:
        return {}
    owners = _asset_owner_ids(session, project)
    owned = session.scalars(
        select(Asset).where(Asset.id.in_(wanted), Asset.owner_user_id.in_(owners))
    )
    return {
        asset.id: {
            "url": media_urls.asset_url(session, asset.id),
            "media_type": asset.media_type,
            "width": asset.width,
            "height": asset.height,
        }
        for asset in owned
    }


def domain_snapshot(session: Session, project: CanvasProject, *, viewer_id: str) -> dict[str, Any]:
    """Everything a drama-mode canvas needs to render, in one read.

    Without this the client would repeat `episode-panel.tsx`'s per-row
    fan-out (`/v1/scripts/{id}`, `/v1/drafts/{id}`, `/v1/works/{id}`) once per
    node — dozens of requests for a ten-episode series — because
    `DramaEpisodeResponse` carries no script and `EpisodeContentLinkResponse`
    carries no title or thumbnail. A free canvas has no domain objects to
    resolve, so it gets empty lists.
    """
    # Assets are resolved in both modes: a free canvas is nothing *but*
    # image and note cards, so skipping them here would leave every uploaded
    # picture blank.
    assets = _node_asset_urls(session, project)
    # Skills bound by the canvas' own cards are resolved in both modes too: a
    # skill card dropped from the prompt library is the whole point of a free
    # canvas' prompt work, and leaving it out is what made such a card render
    # as permanently "stale".
    bound_skills = _bound_skills(session, project, viewer_id=viewer_id)

    if project.series_id is None:
        return {
            "series": None,
            "episodes": [],
            "content_links": [],
            "skills": [_skill_card(session, skill) for skill in bound_skills],
            "assets": assets,
        }

    series = session.get(Series, project.series_id)
    episodes = list(
        session.scalars(
            select(DramaEpisode)
            .where(DramaEpisode.series_id == project.series_id)
            .order_by(DramaEpisode.season_number, DramaEpisode.episode_number)
        )
    )
    episode_ids = [episode.id for episode in episodes]
    links = (
        list(
            session.scalars(
                select(EpisodeContentLink)
                .where(EpisodeContentLink.episode_id.in_(episode_ids))
                .order_by(EpisodeContentLink.created_at)
            )
        )
        if episode_ids
        else []
    )

    return {
        "series": (
            {
                "id": series.id,
                "title": series.title,
                "english_title": series.english_title,
                "status": series.status,
                "planned_episode_count": series.planned_episode_count,
                "genre_tags": list(series.genre_tags_json or []),
                "target_platforms": list(series.target_platforms_json or []),
                "logo_url": media_urls.asset_url(session, series.logo_asset_id),
            }
            if series is not None
            else None
        ),
        "episodes": [
            {
                "id": episode.id,
                "season_number": episode.season_number,
                "episode_number": episode.episode_number,
                "episode_kind": episode.episode_kind,
                "title": episode.title,
                "synopsis": episode.synopsis,
                "status": episode.status,
                "canonical_work_id": episode.canonical_work_id,
                # The whole script document: the client already derives
                # breakpoints from it (`script-breakpoint.ts`), so shipping
                # the document avoids inventing a second breakpoint format
                # that could disagree with the one the script studio uses.
                "script": episode.script_json or None,
            }
            for episode in episodes
        ],
        "content_links": [_hydrate_link(session, link) for link in links],
        "skills": _hydrate_skills(session, episodes, extra=bound_skills),
        "assets": assets,
    }


def _hydrate_link(session: Session, link: EpisodeContentLink) -> dict[str, Any]:
    title: str | None = None
    thumbnail_url: str | None = None
    output_asset_id: str | None = None
    status: str | None = None

    if link.content_type == EpisodeContentType.DRAFT:
        draft = session.get(Draft, link.content_ref_id)
        if draft is not None:
            title = draft.title
            output_asset_id = draft.output_asset_id
            status = draft.publish_status
    elif link.content_type == EpisodeContentType.WORK:
        work = session.get(Work, link.content_ref_id)
        if work is not None:
            status = work.lifecycle_status
            version = (
                session.get(WorkVersion, work.current_version_id)
                if work.current_version_id
                else None
            )
            if version is not None:
                title = version.title
                output_asset_id = version.primary_output_asset_id
                thumbnail_url = media_urls.asset_url(session, version.cover_asset_id)

    if thumbnail_url is None:
        thumbnail_url = media_urls.asset_url(session, output_asset_id)

    return {
        "id": link.id,
        "episode_id": link.episode_id,
        "content_type": link.content_type,
        "content_ref_id": link.content_ref_id,
        "role": link.role,
        "title": title,
        "status": status,
        "output_asset_id": output_asset_id,
        "thumbnail_url": thumbnail_url,
    }


def _bound_skills(
    session: Session, project: CanvasProject, *, viewer_id: str
) -> list[CreationSkill]:
    """Skills the canvas' own cards bind, filtered to what the viewer may see.

    These ids are *client-written* — a card is a row the browser created — so
    unlike `_hydrate_skills`'s episode-derived ids they cannot be trusted.
    Pasting someone else's private skill id into a card must not turn a canvas
    read into a peek at their unpublished draft, exactly as `_node_asset_urls`
    re-checks asset ownership rather than believing the card.

    The predicate is the bulk form of `skill_library_service.get_usable`:
    published is visible to anyone, a draft only to its owner. It is spelled
    out here rather than looped through that helper because a canvas may bind
    up to `MAX_NODES` skills and this runs on every canvas read.

    Visibility, not entitlement: a locked paid skill still shows its card, and
    `assert_unlocked_for_use` remains the gate on actually folding its params
    into a generation.
    """
    wanted = graph_service.bound_skill_ids(session, project.id)
    if not wanted:
        return []
    return list(
        session.scalars(
            select(CreationSkill).where(
                CreationSkill.id.in_(wanted),
                or_(
                    CreationSkill.status == CreationSkillStatus.PUBLISHED,
                    CreationSkill.owner_user_id == viewer_id,
                ),
            )
        )
    )


def _skill_card(session: Session, skill: CreationSkill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "category": skill.category,
        "title": skill.title,
        # The card's own cover when it has one; otherwise its first
        # reference image, which is what a character card usually
        # actually shows.
        "thumbnail_url": media_urls.asset_url(
            session, skill.cover_asset_id or _first_reference_asset_id(skill)
        ),
    }


def _hydrate_skills(
    session: Session, episodes: list[DramaEpisode], *, extra: list[CreationSkill]
) -> list[dict[str, Any]]:
    """Character / scene cards this series' episodes actually reference.

    Deliberately **not** read from `Series.character_ids_json`: that column is
    dead in this codebase (every writer sets `[]` and nothing reads it), so
    keying off it would make the canvas' skill nodes permanently empty. The
    live sources are each episode's `source_referenced_skill_ids_json` (what
    script writing was given) plus the `character_ref_id` / scene `ref_id`
    values the script document itself carries after linking.

    These are `CreationSkill` ids, not foreign keys (characters and scenes are
    `CreationSkill` rows — see the `zaolang-data-model` skill), so an id
    with no surviving row is simply skipped.
    """
    skill_ids: list[str] = []
    seen: set[str] = set()

    def remember(value: Any) -> None:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            skill_ids.append(value)

    for episode in episodes:
        for sid in episode.source_referenced_skill_ids_json or []:
            remember(sid)
        script = episode.script_json or {}
        for character in script.get("characters") or []:
            if isinstance(character, dict):
                remember(character.get("character_ref_id"))
        for scene in script.get("scenes") or []:
            if isinstance(scene, dict):
                remember(scene.get("ref_id"))

    skills = (
        list(session.scalars(select(CreationSkill).where(CreationSkill.id.in_(skill_ids))))
        if skill_ids
        else []
    )
    # `extra` are the canvas' own node-bound skills, already access-checked by
    # `_bound_skills`. Merged here rather than concatenated by the caller so a
    # skill that is both referenced by a script and dropped on the canvas
    # appears once.
    for skill in extra:
        if skill.id not in seen:
            seen.add(skill.id)
            skills.append(skill)
    return [_skill_card(session, skill) for skill in skills]


def _first_reference_asset_id(skill: CreationSkill) -> str | None:
    params = skill.params_json or {}
    for bucket in ("character", "scene"):
        section = params.get(bucket)
        if not isinstance(section, dict):
            continue
        refs = section.get("reference_assets")
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, dict) and isinstance(ref.get("asset_id"), str):
                    return ref["asset_id"]
                if isinstance(ref, str):
                    return ref
    return None
