"""Conversational short-drama script writing.

Turns an idea into a full scene-by-scene script, then revises it turn by
turn through the `copy` agent's `script_draft`/`script_revise` slots
(`app.agents.copywriter`). Reuses the drama editor's own models —
`Series`/`DramaEpisode` — rather than a new entity: `DramaEpisode.script_json`
was an unused placeholder before this (see `.cursor/skills/zaolang-editor-drama`).
`EpisodeScriptTurn` is the one new table, an append-only chain (mirroring
`CutRevision`) that exists purely so a user can click back into any earlier
turn and see the exact script it produced; `script_json` itself always holds
the latest turn's snapshot.

Gated by its own `script_studio_enabled` flag, deliberately not
`app.domain.editor.flags.FLAG_DRAMA`: script writing should be able to ship,
or be turned off, independently of the full episode/cut editor. Both flags
happen to guard the same tables, which is intentional — a script written
here is a normal `DramaEpisode` an author can later open in the drama editor
to generate cuts from.

Streaming turns split into two phases for a reason that has nothing to do
with the domain and everything to do with FastAPI: a `StreamingResponse`'s
generator runs *after* the route handler returns, by which point FastAPI has
already closed the request-scoped `DbSession` dependency. `prepare_new_script`
/`prepare_turn` do all validation and ownership checks against that
request-scoped session (fast, and safe to run inside the handler); the
caller commits that, then `stream_new_script`/`stream_turn` open their own
session for the life of the stream via `app.db.session_scope` — the same
tool workers and one-off scripts use for exactly this "outlives the request"
reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.db import session_scope
from app.domain.characters import service as characters_service
from app.domain.errors import DomainError, NotFound, ValidationFailed
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.models import DramaEpisode, EpisodeScriptTurn, Series
from app.models.enums import DramaEpisodeStatus, SeriesKind, SeriesStatus
from app.platform_config import service as config_service

SCRIPT_STUDIO_FLAG = "script_studio_enabled"
MAX_REFERENCED_SKILLS = 5
MAX_IDEA_LEN = 2000
MAX_MESSAGE_LEN = 2000
MAX_TITLE_LEN = 60


def _require_script_studio(session: Session, *, user_id: str | None) -> None:
    if not config_service.is_enabled(session, SCRIPT_STUDIO_FLAG, user_id=user_id):
        raise NotFound("该功能暂未开放。")


def _owned_episode(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    episode = session.get(DramaEpisode, episode_id)
    if episode is None:
        raise NotFound("剧本不存在。")
    series = session.get(Series, episode.series_id)
    if series is None or series.owner_user_id != user_id:
        raise NotFound("剧本不存在。")
    return episode


def _resolve_referenced_skills(
    session: Session, *, user_id: str, skill_ids: list[str] | None
) -> list[dict[str, str]]:
    """Fetches title/description for referenced skills as style hints.

    Any skill the viewer can see and has unlocked is fair game — script
    writing does not filter by `applicable_operations` the way a
    parameter-applying flow does: a skill's `params` (image/video generation
    settings) have no direct meaning for text, only its title/description
    carry over, as a style reference woven into the prompt.
    """
    ids = list(dict.fromkeys(skill_ids or []))[:MAX_REFERENCED_SKILLS]
    referenced: list[dict[str, str]] = []
    for skill_id in ids:
        skill = skill_library_service.get_usable(session, skill_id=skill_id, viewer_id=user_id)
        skill_library_service.assert_unlocked_for_use(session, skill, user_id)
        skill_library_service.record_usage(session, skill=skill)
        referenced.append(
            {"id": skill.id, "title": skill.title, "description": skill.description or ""}
        )
    return referenced


def _skill_hints(referenced: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"title": s["title"], "description": s["description"]} for s in referenced]


@dataclass(slots=True)
class NewScriptPrep:
    episode_id: str
    title: str
    idea: str
    referenced_skills: list[dict[str, str]]


@dataclass(slots=True)
class TurnPrep:
    episode_id: str
    message: str
    current_script: dict[str, Any]
    referenced_skills: list[dict[str, str]]
    next_turn_no: int
    parent_turn_id: str | None


@dataclass(slots=True)
class TurnResult:
    """Filled in place by `stream_new_script`/`stream_turn` as their
    generator runs; only meaningful once the generator is fully drained."""

    turn_id: str = ""
    turn_no: int = 0
    summary: str = ""
    script: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    error: str | None = None


def prepare_new_script(
    session: Session,
    *,
    user_id: str,
    title: str,
    idea: str,
    referenced_skill_ids: list[str] | None = None,
) -> NewScriptPrep:
    """Validates input and creates the `Series`+`DramaEpisode` shell.

    The caller must `session.commit()` this before starting the stream —
    `stream_new_script` looks the episode up again from a different DB
    session/connection.
    """
    _require_script_studio(session, user_id=user_id)
    idea = idea.strip()[:MAX_IDEA_LEN]
    if not idea:
        raise ValidationFailed("请先描述你的创意。")
    title = title.strip()[:MAX_TITLE_LEN]
    referenced = _resolve_referenced_skills(
        session, user_id=user_id, skill_ids=referenced_skill_ids
    )

    series = Series(
        owner_user_id=user_id,
        title=title or idea[:24],
        description=None,
        character_ids_json=[],
        kind=SeriesKind.DRAMA,
        default_locale="zh-CN",
        status=SeriesStatus.ACTIVE,
        allow_external_models=False,
    )
    session.add(series)
    session.flush()

    episode = DramaEpisode(
        series_id=series.id,
        episode_number=1,
        title=title or idea[:24] or "未命名短剧",
        synopsis=None,
        script_json={},
        status=DramaEpisodeStatus.DRAFT,
    )
    session.add(episode)
    session.flush()

    return NewScriptPrep(
        episode_id=episode.id, title=title, idea=idea, referenced_skills=referenced
    )


def prepare_turn(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    message: str,
    referenced_skill_ids: list[str] | None = None,
    client_script: dict[str, Any] | None = None,
) -> TurnPrep:
    """Validates ownership/input. No write happens here — a turn is only
    ever created once its stream finishes (see `stream_turn`).

    `client_script`, when given, is the exact document the caller is looking
    at (usually the latest turn, but possibly one the user has browsed back
    to) — see `ScriptTurnRequest.current_script`. It is re-validated through
    the same sanitizer the model's own output goes through rather than
    trusted verbatim, then used as the revision's basis instead of
    `episode.script_json`, so a turn always continues from whatever is
    actually on screen. Omitting it keeps today's behavior of always
    continuing from the episode's true latest turn.
    """
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    message = message.strip()[:MAX_MESSAGE_LEN]
    if not message:
        raise ValidationFailed("请描述你想要的修改。")
    current_script = (
        (copywriter._sanitize_script(client_script) if client_script is not None else None)
        or episode.script_json
        or {}
    )
    if not current_script:
        raise ValidationFailed("该剧本还没有初稿，请先生成初稿。")

    last_turn = session.scalar(
        select(EpisodeScriptTurn)
        .where(EpisodeScriptTurn.episode_id == episode.id)
        .order_by(EpisodeScriptTurn.turn_no.desc())
        .limit(1)
    )
    referenced = _resolve_referenced_skills(
        session, user_id=user_id, skill_ids=referenced_skill_ids
    )
    return TurnPrep(
        episode_id=episode.id,
        message=message,
        current_script=current_script,
        referenced_skills=referenced,
        next_turn_no=(last_turn.turn_no + 1) if last_turn else 1,
        parent_turn_id=last_turn.id if last_turn else None,
    )


def stream_new_script(prep: NewScriptPrep, *, user_id: str, result: TurnResult) -> Iterator[str]:
    """SSE generator for a script's first turn.

    Opens its own DB session for the life of the stream — see the module
    docstring for why the request-scoped session cannot be reused here.
    """
    with session_scope() as session:
        try:
            chunks, finalize_turn = copywriter.stream_draft_script(
                session,
                idea=prep.idea,
                title=prep.title,
                referenced_skills=_skill_hints(prep.referenced_skills),
                user_id=user_id,
            )
            yield from chunks

            outcome = finalize_turn()
            if not outcome.parse_ok:
                # Unlike a revision, a first draft has no prior version to
                # fall back to — `stream_draft_script.finalize` covers that
                # gap with an empty-scenes placeholder so the caller always
                # gets *a* dict back. Persisting that placeholder as a turn
                # would look identical to a real, finished script (an
                # episode with one turn and a non-empty `script_json`), so
                # the "no turns yet" retry UI built for a still-streaming or
                # truly-missing draft would never catch it. Surfacing it as
                # an `error` frame instead — nothing written, episode stays
                # exactly as `prepare_new_script` left it — is what actually
                # lets the user retry.
                result.error = outcome.summary or "剧本生成失败，请换一种方式描述你的创意后重试。"
                return

            episode = session.get(DramaEpisode, prep.episode_id)
            if episode is None:
                raise NotFound("剧本不存在。")

            turn = EpisodeScriptTurn(
                episode_id=prep.episode_id,
                turn_no=1,
                parent_turn_id=None,
                user_id=user_id,
                user_message=prep.idea,
                summary=outcome.summary,
                script_snapshot_json=outcome.script,
                referenced_skill_ids_json=[s["id"] for s in prep.referenced_skills],
                agent_run_id=outcome.agent_run_id,
            )
            session.add(turn)
            episode.script_json = outcome.script
            if not prep.title and outcome.script.get("title"):
                episode.title = str(outcome.script["title"])[:200]
            session.flush()

            result.turn_id = turn.id
            result.turn_no = turn.turn_no
            result.summary = outcome.summary
            result.script = outcome.script
            result.degraded = outcome.degraded
        except DomainError as exc:
            session.rollback()
            result.error = exc.message
        except Exception as exc:
            # A failed flush/execute leaves the session unable to do anything
            # else — including `session_scope`'s own commit on the way out —
            # until it is rolled back. Without this, a DB error here doesn't
            # surface as a clean `error` frame: `session_scope` re-raises
            # `PendingRollbackError` while closing, which propagates out of
            # this generator entirely and kills the stream with no closing
            # frame at all (delta events arrive, then the connection just
            # ends) — the caller never learns why.
            session.rollback()
            result.error = str(exc)


def stream_turn(prep: TurnPrep, *, user_id: str, result: TurnResult) -> Iterator[str]:
    """SSE generator for a revision turn. Same session-lifetime rationale as
    `stream_new_script`; the fallback on any failure is `prep.current_script`
    staying exactly as it was — handled inside `copywriter.stream_revise_script`
    itself, not here."""
    with session_scope() as session:
        try:
            chunks, finalize_turn = copywriter.stream_revise_script(
                session,
                message=prep.message,
                current_script=prep.current_script,
                referenced_skills=_skill_hints(prep.referenced_skills),
                user_id=user_id,
            )
            yield from chunks

            outcome = finalize_turn()
            episode = session.get(DramaEpisode, prep.episode_id)
            if episode is None:
                raise NotFound("剧本不存在。")

            turn = EpisodeScriptTurn(
                episode_id=prep.episode_id,
                turn_no=prep.next_turn_no,
                parent_turn_id=prep.parent_turn_id,
                user_id=user_id,
                user_message=prep.message,
                summary=outcome.summary,
                script_snapshot_json=outcome.script,
                referenced_skill_ids_json=[s["id"] for s in prep.referenced_skills],
                agent_run_id=outcome.agent_run_id,
            )
            session.add(turn)
            episode.script_json = outcome.script
            session.flush()

            result.turn_id = turn.id
            result.turn_no = turn.turn_no
            result.summary = outcome.summary
            result.script = outcome.script
            result.degraded = outcome.degraded
        except DomainError as exc:
            session.rollback()
            result.error = exc.message
        except Exception as exc:
            session.rollback()
            result.error = str(exc)


def list_scripts(session: Session, *, user_id: str) -> list[DramaEpisode]:
    """Only episodes that have gone through this flow at least once (i.e.
    have a turn) — a `DramaEpisode` created straight from the drama editor
    with an empty `script_json` is not "a script in progress" here."""
    _require_script_studio(session, user_id=user_id)
    stmt = (
        select(DramaEpisode)
        .join(Series, Series.id == DramaEpisode.series_id)
        .where(
            Series.owner_user_id == user_id,
            Series.kind == SeriesKind.DRAMA,
            exists().where(EpisodeScriptTurn.episode_id == DramaEpisode.id),
        )
        .order_by(DramaEpisode.updated_at.desc())
    )
    return list(session.scalars(stmt))


def get_script(
    session: Session, *, user_id: str, episode_id: str
) -> tuple[DramaEpisode, list[EpisodeScriptTurn]]:
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    turns = list(
        session.scalars(
            select(EpisodeScriptTurn)
            .where(EpisodeScriptTurn.episode_id == episode.id)
            .order_by(EpisodeScriptTurn.turn_no.asc())
        )
    )
    return episode, turns


def get_turn_snapshot(
    session: Session, *, user_id: str, episode_id: str, turn_id: str
) -> EpisodeScriptTurn:
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    turn = session.get(EpisodeScriptTurn, turn_id)
    if turn is None or turn.episode_id != episode.id:
        raise NotFound("该版本不存在。")
    return turn


def update_links(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    character_links: list[tuple[str, str | None]],
    scene_links: list[tuple[str, str | None]],
) -> DramaEpisode:
    """Links a script's characters/scene headings to reusable `Character`/
    `Scene` assets — a structural edit, not a content revision, so it writes
    directly to `episode.script_json` without going through the LLM turn
    machinery: no `AgentRun`, no new `EpisodeScriptTurn`, no model call spent
    on something the user decided by clicking a picker rather than describing
    in words (see ask #2's "always a full LLM turn" — deliberately scoped to
    content changes only).

    Matches by `name`/`heading` rather than position, same trade-off
    `copywriter._carry_over_links` makes: whichever character/scene the
    caller named survives even if the LLM has since reordered the lists,
    but a name that no longer exists in the current script is silently a
    no-op rather than an error — the client's view of names may be one turn
    stale by the time this lands.
    """
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    script = episode.script_json or {}
    if not script:
        raise ValidationFailed("该剧本还没有初稿，请先生成初稿。")

    character_ref_by_name = dict(character_links)
    for ref_id in character_ref_by_name.values():
        if ref_id:
            characters_service.get_character(session, user_id=user_id, character_id=ref_id)
    scene_ref_by_heading = dict(scene_links)
    for ref_id in scene_ref_by_heading.values():
        if ref_id:
            scenes_service.get_scene(session, user_id=user_id, scene_id=ref_id)

    next_characters = []
    for item in script.get("characters") or []:
        item = dict(item)
        if item.get("name") in character_ref_by_name:
            item["character_ref_id"] = character_ref_by_name[item["name"]]
        next_characters.append(item)

    next_scenes = []
    for scene in script.get("scenes") or []:
        scene = dict(scene)
        if scene.get("heading") in scene_ref_by_heading:
            scene["ref_id"] = scene_ref_by_heading[scene["heading"]]
        next_scenes.append(scene)

    # A fresh dict, not a mutated nested one — SQLAlchemy only detects a
    # JSONB column change on reassignment, matching how every other turn
    # here writes `episode.script_json` (see `stream_new_script`/`stream_turn`).
    episode.script_json = {**script, "characters": next_characters, "scenes": next_scenes}
    session.flush()
    return episode
