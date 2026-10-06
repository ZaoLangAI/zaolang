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

Streaming turns split for a reason that has nothing to do with the domain
and everything to do with FastAPI: a `StreamingResponse`'s generator runs
*after* the route handler returns, by which point FastAPI has already closed
the request-scoped `DbSession` dependency. `prepare_new_script`/`prepare_turn`
do all validation and ownership checks against that request-scoped session
(fast, and safe to run inside the handler); the caller commits that before
the generator starts.

`stream_new_script`/`stream_turn` then use two short `session_scope()`
windows — one to resolve the prompt/binding and snapshot the LLM endpoint
list, one to persist the `AgentRun` + turn *after* the stream drains. The
LLM call itself holds no DB connection, so a 60s thinking model cannot sit
`idle in transaction` and starve `GET /v1/scripts/{id}`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.agents import copywriter, skill_matcher
from app.db import session_scope
from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters import service as characters_service
from app.domain.editor import collaborators
from app.domain.editor import service as editor_service
from app.domain.errors import DomainError, NotFound, ValidationFailed
from app.domain.notifications import push
from app.domain.props import service as props_service
from app.domain.scenes import service as scenes_service
from app.domain.script_writing.extract import ExtractedScriptSource, extract_script_source
from app.domain.skill_library import service as skill_library_service
from app.llm.client import StreamChunk
from app.models import AgentRun, DramaEpisode, EpisodeScriptTurn, Notification, Series
from app.models.enums import DramaEpisodeStatus, SeriesKind, SeriesStatus
from app.platform_config import service as config_service

SCRIPT_STUDIO_FLAG = "script_studio_enabled"
MAX_REFERENCED_SKILLS = 5
MAX_IDEA_LEN = 20_000
MAX_MESSAGE_LEN = 2000
MAX_TITLE_LEN = 60
# How far after `DramaEpisode.created_at` a `script_draft` AgentRun still
# counts as *this* empty shell's original attempt — AgentRun has no
# episode_id, so a later draft for a different episode by the same user
# must not be attributed here. The stream's own wall clock is 600s per
# attempt (plus one same-endpoint retry); this window is just wide enough
# for a slow thinking model plus that retry, not a next-day session on
# another script.
_SOURCE_IDEA_RECOVER_WINDOW = timedelta(minutes=30)


def _require_script_studio(session: Session, *, user_id: str | None) -> None:
    if not config_service.is_enabled(session, SCRIPT_STUDIO_FLAG, user_id=user_id):
        raise NotFound("该功能暂未开放。")


def extract_uploaded_script(
    session: Session,
    *,
    user_id: str,
    filename: str,
    payload: bytes,
    mime_type: str = "",
) -> ExtractedScriptSource:
    """Flag-gated wrapper around `extract.extract_script_source`."""
    _require_script_studio(session, user_id=user_id)
    return extract_script_source(
        session,
        user_id=user_id,
        filename=filename,
        payload=payload,
        mime_type=mime_type,
    )


def _owned_episode(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    """Despite the name, this is the *accessible* check (owner or active
    co-creator) — script writing is part of the management-level surface a
    共创 collaborator gets full access to, same as basic episode CRUD
    (`editor_service._accessible_episode`). See `zaolang-editor-drama`."""
    episode = session.get(DramaEpisode, episode_id)
    if episode is None:
        raise NotFound("剧本不存在。")
    series = session.get(Series, episode.series_id)
    if series is None:
        raise NotFound("剧本不存在。")
    if series.owner_user_id != user_id and not collaborators.is_active_member(
        session, user_id=user_id, series_id=series.id
    ):
        raise NotFound("剧本不存在。")
    return episode


def _notify_script(
    session: Session,
    episode: DramaEpisode,
    *,
    status: str,
    kind: str,
    series: Series | None = None,
    turn_no: int | None = None,
    error: str | None = None,
) -> None:
    """Upserts the one notification row for `episode`'s most recent
    generation attempt, using `session` as-is (must be healthy — never
    called right after a `session.rollback()` on this same session, see
    `_notify_script_failure` for that case). Pass `series` when the caller
    already has it loaded (`prepare_new_script`'s freshly created/looked-up
    one); otherwise this loads it itself. A missing `Series` (should never
    happen — every `DramaEpisode` here always has one) degrades to a no-op
    rather than raising, since a notification is never allowed to be the
    reason a script request fails."""
    series = series or session.get(Series, episode.series_id)
    if series is None:
        return
    push.sync_script_notification(
        session,
        episode=episode,
        series=series,
        status=status,
        kind=kind,
        turn_no=turn_no,
        error=error,
    )


def _notify_script_failure(episode_id: str, *, kind: str, error: str) -> None:
    """Same as `_notify_script(status="failed")`, but opens its own fresh
    session instead of reusing the caller's — for the two situations where
    that session is either not open yet (the LLM call itself raised, before
    `stream_new_script`/`stream_turn` ever open their persist-phase session)
    or was just rolled back by the caller's own `except` block (reusing a
    session immediately after `rollback()` here is avoidable complexity
    this skips entirely)."""
    with session_scope() as session:
        episode = session.get(DramaEpisode, episode_id)
        if episode is None:
            return
        _notify_script(session, episode, status="failed", kind=kind, error=error)


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


def _topped_up_with_matches(
    session: Session, *, user_id: str, brief: str, picked: list[dict[str, str]]
) -> list[dict[str, str]]:
    """`picked` first, then seeded `drama` skills the matcher found for
    `brief`, up to `MAX_REFERENCED_SKILLS`.

    The user's own `@` references always keep their slots — an automatic
    suggestion may never displace an explicit choice — and the matcher is
    told about them (`exclude_ids`) so it doesn't spend a pick re-choosing
    one.

    The result is prompt-facing only. `_store_source_prompt` keeps recording
    the user's ids alone, because a matched id written there would come back
    through `_resolve_referenced_skills` on the next retry and be charged
    and counted as if the user had picked it.
    """
    remaining = MAX_REFERENCED_SKILLS - len(picked)
    if remaining <= 0:
        return picked
    matched_ids = skill_matcher.select_reference_skills(
        session,
        brief=brief,
        limit=remaining,
        exclude_ids=tuple(entry["id"] for entry in picked),
        user_id=user_id,
    )
    return picked + skill_library_service.load_reference_skills(session, matched_ids)


def _store_source_prompt(episode: DramaEpisode, *, idea: str, skill_ids: list[str]) -> None:
    episode.source_idea = idea
    episode.source_referenced_skill_ids_json = list(skill_ids)


def _idea_from_agent_run(run: AgentRun) -> tuple[str, list[str]]:
    """Unpacks `stream_draft_script`'s JSON user_prompt back into idea + ids."""
    raw = (run.input_json or {}).get("user_prompt")
    payload: Any
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return "", []
    else:
        return "", []
    if not isinstance(payload, dict):
        return "", []
    idea = str(payload.get("idea") or "").strip()[:MAX_IDEA_LEN]
    skills = payload.get("referenced_skills") or []
    ids: list[str] = []
    if isinstance(skills, list):
        for item in skills[:MAX_REFERENCED_SKILLS]:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    return idea, ids


def _hydrate_source_idea(session: Session, *, episode: DramaEpisode, user_id: str) -> None:
    """Fills `source_idea` on a historical empty shell from a nearby run.

    New shells persist the idea in `prepare_new_script`. Episodes created
    before that column existed still have a `script_draft` AgentRun whose
    `input_json.user_prompt` carries the original idea — recover it so the
    empty-shell page can one-click retry. No-op when the idea is already
    stored, or when the episode already has a turn (retry is blocked then).
    """
    if (episode.source_idea or "").strip():
        return
    has_turn = session.scalar(select(exists().where(EpisodeScriptTurn.episode_id == episode.id)))
    if has_turn:
        return
    window_start = episode.created_at - timedelta(seconds=30)
    window_end = episode.created_at + _SOURCE_IDEA_RECOVER_WINDOW
    run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.user_id == user_id,
            AgentRun.prompt_slot == copywriter.SCRIPT_DRAFT_SLOT,
            AgentRun.created_at >= window_start,
            AgentRun.created_at <= window_end,
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return
    idea, skill_ids = _idea_from_agent_run(run)
    if not idea:
        return
    _store_source_prompt(episode, idea=idea, skill_ids=skill_ids)
    session.flush()


def script_last_error(session: Session, *, episode_id: str) -> str | None:
    """The most recent failed-generation excerpt for this episode, if any."""
    note = session.scalar(
        select(Notification)
        .where(
            Notification.target_type == push.CREATION_TARGET_SCRIPT,
            Notification.target_id == episode_id,
        )
        .limit(1)
    )
    if note is None:
        return None
    error = (note.payload_json or {}).get("error")
    if not isinstance(error, str) or not error.strip():
        return None
    return error.strip()


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
    thinking: str = ""
    error: str | None = None


def prepare_new_script(
    session: Session,
    *,
    user_id: str,
    title: str,
    idea: str,
    referenced_skill_ids: list[str] | None = None,
    series_id: str | None = None,
) -> NewScriptPrep:
    """Validates input and creates the `DramaEpisode` shell.

    When `series_id` is given, the new episode is attached to that existing
    `kind=drama` series instead of spinning up a new one — this is the
    "新增一集" entry point from the drama-series management module's series
    detail page, which must not silently create a second series. Without a
    `series_id` (the standalone `/create/script` idea-input flow), a new
    `Series`+episode shell is created together, unchanged from before.

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

    if series_id:
        series = session.get(Series, series_id)
        if series is None:
            raise NotFound("剧集不存在。")
        if series.owner_user_id != user_id and not collaborators.is_active_member(
            session, user_id=user_id, series_id=series.id
        ):
            raise NotFound("剧集不存在。")
        if series.kind != SeriesKind.DRAMA:
            raise ValidationFailed("该系列不是短剧制作项目。")
    else:
        series = Series(
            owner_user_id=user_id,
            title=title or idea[:24],
            description=None,
            character_ids_json=[],
            kind=SeriesKind.DRAMA,
            default_locale="zh-CN",
            status=SeriesStatus.ACTIVE,
            allow_external_models=False,
            target_platforms_json=[],
            genre_tags_json=[],
        )
        session.add(series)
        session.flush()

    next_number = (
        session.scalar(
            select(DramaEpisode.episode_number)
            .where(DramaEpisode.series_id == series.id, DramaEpisode.season_number == 1)
            .order_by(DramaEpisode.episode_number.desc())
        )
        or 0
    ) + 1

    episode = DramaEpisode(
        series_id=series.id,
        episode_number=next_number,
        title=title or idea[:24] or "未命名短剧",
        synopsis=None,
        script_json={},
        status=DramaEpisodeStatus.DRAFT,
    )
    session.add(episode)
    session.flush()
    _store_source_prompt(episode, idea=idea, skill_ids=[s["id"] for s in referenced])
    _notify_script(session, episode, status="generating", kind="draft", series=series)

    return NewScriptPrep(
        episode_id=episode.id,
        title=title,
        idea=idea,
        referenced_skills=_topped_up_with_matches(
            session, user_id=user_id, brief=idea, picked=referenced
        ),
    )


def retry_new_script(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    idea: str | None = None,
    referenced_skill_ids: list[str] | None = None,
) -> NewScriptPrep:
    """Re-runs the first-draft stream for an episode shell that
    `prepare_new_script` already created but that never got a finished turn
    — a page refresh or a dropped connection mid-stream loses
    `create-stream-store.ts`'s in-memory progress.

    `idea` is optional: a blank/omitted value reuses `episode.source_idea`
    (persisted on create, or recovered from a nearby `script_draft`
    AgentRun for shells that predate that column). Sending a new idea
    overwrites the stored prompt so the next retry can omit the body.

    Deliberately does not call `prepare_new_script` again: that always mints
    a brand-new `Series`+`DramaEpisode` pair, which would leave the original
    empty shell behind as an orphaned duplicate every time a user retries.
    Blocked once the episode already has a turn — that is no longer an empty
    shell, and revising it belongs to `prepare_turn`/`stream_turn` instead.
    """
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    has_turn = session.scalar(select(exists().where(EpisodeScriptTurn.episode_id == episode.id)))
    if has_turn:
        raise ValidationFailed("该剧本已生成初稿，无法重新生成。")
    _hydrate_source_idea(session, episode=episode, user_id=user_id)
    idea = (idea or "").strip()[:MAX_IDEA_LEN] or (episode.source_idea or "").strip()[:MAX_IDEA_LEN]
    if not idea:
        raise ValidationFailed("请先描述你的创意。")
    skill_ids = list(referenced_skill_ids or []) or list(
        episode.source_referenced_skill_ids_json or []
    )
    referenced = _resolve_referenced_skills(session, user_id=user_id, skill_ids=skill_ids)
    _store_source_prompt(episode, idea=idea, skill_ids=[s["id"] for s in referenced])
    _notify_script(session, episode, status="generating", kind="draft")
    # `title=""`, not `episode.title`: `prepare_new_script` already filled
    # `episode.title` with a fallback (`idea[:24]` or "未命名短剧") since a
    # title is never actually optional on the row, so reusing it here would
    # permanently block `stream_new_script`'s own "no title given yet" path
    # (`if not prep.title and outcome.script.get("title")`) from ever
    # applying the model's real title on a successful retry.
    return NewScriptPrep(
        episode_id=episode.id,
        title="",
        idea=idea,
        referenced_skills=_topped_up_with_matches(
            session, user_id=user_id, brief=idea, picked=referenced
        ),
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
    _notify_script(session, episode, status="generating", kind="revise")
    return TurnPrep(
        episode_id=episode.id,
        message=message,
        current_script=current_script,
        # The revision note alone ("把第三场写得更紧张") rarely names a scene
        # type or an emotion, so the logline rides along as the story the
        # matcher is actually matching against.
        referenced_skills=_topped_up_with_matches(
            session,
            user_id=user_id,
            brief=f"{str(current_script.get('logline') or '').strip()}\n{message}".strip(),
            picked=referenced,
        ),
        next_turn_no=(last_turn.turn_no + 1) if last_turn else 1,
        parent_turn_id=last_turn.id if last_turn else None,
    )


def stream_new_script(
    prep: NewScriptPrep, *, user_id: str, result: TurnResult
) -> Iterator[StreamChunk]:
    """SSE generator for a script's first turn.

    Forwards `copywriter.stream_draft_script`'s chunks unchanged — each is
    already a typed `StreamChunk` (`kind="content"` for the chat bubble,
    `kind="thinking"` for the model's live reasoning); the API layer
    (`app.api.v1.scripts`) is what turns `.kind` into an SSE event name.

    Resolve + endpoint lookup happen in a short session; the LLM stream
    itself holds no DB connection; persist opens a second session. See the
    module docstring for why none of this can reuse the request-scoped
    session.
    """
    try:
        with session_scope() as session:
            chunks, finalize_turn = copywriter.stream_draft_script(
                session,
                idea=prep.idea,
                title=prep.title,
                referenced_skills=_skill_hints(prep.referenced_skills),
                user_id=user_id,
            )
        yield from chunks
    except DomainError as exc:
        result.error = exc.message
        _notify_script_failure(prep.episode_id, kind="draft", error=result.error)
        return
    except Exception as exc:
        result.error = str(exc)
        _notify_script_failure(prep.episode_id, kind="draft", error=result.error)
        return

    with session_scope() as session:
        try:
            outcome = finalize_turn(session)
            episode = session.get(DramaEpisode, prep.episode_id)
            if episode is None:
                raise NotFound("剧本不存在。")

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
                _notify_script(session, episode, status="failed", kind="draft", error=result.error)
                return

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
                thinking_text=outcome.thinking,
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
            result.thinking = outcome.thinking
            _notify_script(session, episode, status="succeeded", kind="draft", turn_no=turn.turn_no)
        except DomainError as exc:
            session.rollback()
            result.error = exc.message
            _notify_script_failure(prep.episode_id, kind="draft", error=result.error)
        except Exception as exc:
            session.rollback()
            result.error = str(exc)
            _notify_script_failure(prep.episode_id, kind="draft", error=result.error)


def stream_turn(prep: TurnPrep, *, user_id: str, result: TurnResult) -> Iterator[StreamChunk]:
    """SSE generator for a revision turn. Same session-lifetime split as
    `stream_new_script`; the fallback on any failure is `prep.current_script`
    staying exactly as it was — handled inside `copywriter.stream_revise_script`
    itself, not here."""
    try:
        with session_scope() as session:
            chunks, finalize_turn = copywriter.stream_revise_script(
                session,
                message=prep.message,
                current_script=prep.current_script,
                referenced_skills=_skill_hints(prep.referenced_skills),
                user_id=user_id,
            )
        yield from chunks
    except DomainError as exc:
        result.error = exc.message
        _notify_script_failure(prep.episode_id, kind="revise", error=result.error)
        return
    except Exception as exc:
        result.error = str(exc)
        _notify_script_failure(prep.episode_id, kind="revise", error=result.error)
        return

    with session_scope() as session:
        try:
            outcome = finalize_turn(session)
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
                thinking_text=outcome.thinking,
            )
            session.add(turn)
            episode.script_json = outcome.script
            session.flush()

            result.turn_id = turn.id
            result.turn_no = turn.turn_no
            result.summary = outcome.summary
            result.script = outcome.script
            result.degraded = outcome.degraded
            result.thinking = outcome.thinking
            _notify_script(
                session, episode, status="succeeded", kind="revise", turn_no=turn.turn_no
            )
        except DomainError as exc:
            session.rollback()
            result.error = exc.message
            _notify_script_failure(prep.episode_id, kind="revise", error=result.error)
        except Exception as exc:
            session.rollback()
            result.error = str(exc)
            _notify_script_failure(prep.episode_id, kind="revise", error=result.error)


def list_scripts(session: Session, *, user_id: str) -> list[DramaEpisode]:
    """Every `kind=drama` episode the caller owns **or actively co-creates**,
    including a 0-turn shell whose first draft is still streaming (in
    another tab/device) or failed outright — `prepare_new_script`/
    `retry_new_script` are the only paths that create such a shell today
    (the drama editor's own `POST /v1/drama-series/{id}/episodes` has no
    frontend caller), so dropping the "has a turn" requirement no longer
    hides a script the user is actively waiting on or needs to retry; the
    caller renders a 0-turn row differently via `turn_count == 0` rather
    than this list silently excluding it.

    Excludes episodes whose series is in the recycle bin, mirroring
    `list_drama_series`' default — trashing a series should hide its
    scripts from this general list too, not just from the series dashboard;
    a direct link to the episode still works, same as the dashboard's own
    trashed-series detail page. A co-creator has no trash rights, so this
    only ever excludes on the *owner's* trash state, same as
    `list_drama_series`."""
    _require_script_studio(session, user_id=user_id)
    collab_series_ids = collaborators.collaborator_series_ids(session, user_id=user_id)
    owner_or_collaborator = (
        or_(Series.owner_user_id == user_id, Series.id.in_(collab_series_ids))
        if collab_series_ids
        else Series.owner_user_id == user_id
    )
    stmt = (
        select(DramaEpisode)
        .join(Series, Series.id == DramaEpisode.series_id)
        .where(
            owner_or_collaborator,
            Series.kind == SeriesKind.DRAMA,
            Series.status != SeriesStatus.TRASHED,
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
    if not turns:
        _hydrate_source_idea(session, episode=episode, user_id=user_id)
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


def delete_script(session: Session, *, user_id: str, episode_id: str) -> None:
    """Deletes a script (its `DramaEpisode`) the caller owns or actively
    co-creates — same access rule as `editor_service.delete_episode`.

    A published episode (`canonical_work_id` set) still 422s — that work
    is the public projection. Unpublished `EpisodeCut` rows are torn down
    first via `purge_unpublished_editor_graph` so the `RESTRICT` on
    `episode_cuts.episode_id` does not surface as a raw `IntegrityError`.
    `EpisodeScriptTurn` rows cascade automatically (`ondelete="CASCADE"`).

    The owning `Series` is never hard-deleted here — that is
    `editor_service.purge_drama_series`' job, behind the recycle bin. The
    only series-level side effect is tidying up the shell the standalone
    `/create/script` flow auto-creates (`prepare_new_script` without a
    `series_id`): once its last episode is gone, it is moved to the
    owner's recycle bin (`trash_drama_series`) instead of lingering as an
    empty card on the dashboard, and the owner can still restore or purge
    it from there. That happens only when all of these hold:

    - no other `DramaEpisode` still references the series;
    - the caller is the series owner — a co-creator never gets trash
      rights (see `zaolang-editor-drama`), so their delete leaves the
      owner's series alone;
    - the series is still an uncurated shell, i.e. `target_platforms_json`
      is empty. The series form (`create_drama_series`/`update_drama_series`)
      always requires at least one platform, so a non-empty list means it
      was created on, or since edited through, the `/create/short`
      dashboard and must stay put, same as after `delete_episode`;
    - it is not already in the recycle bin.
    """
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    if episode.canonical_work_id is not None:
        raise ValidationFailed("已发布的剧本不能删除。")
    editor_service.purge_unpublished_editor_graph(session, episode)

    series_id = episode.series_id
    session.delete(episode)
    session.flush()

    series = session.get(Series, series_id)
    if (
        series is None
        or series.owner_user_id != user_id
        or series.target_platforms_json
        or series.status == SeriesStatus.TRASHED
    ):
        return
    other_episode_exists = session.scalar(
        select(exists().where(DramaEpisode.series_id == series_id))
    )
    if not other_episode_exists:
        editor_service.trash_drama_series(session, user_id=user_id, series_id=series_id)


def update_links(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    character_links: list[tuple[str, str | None, str | None]],
    scene_links: list[tuple[str, str | None, str | None]],
    prop_links: list[tuple[str, str | None]] | None = None,
) -> DramaEpisode:
    """Links a script's characters/scene headings/props to reusable
    character/scene/prop cards — a structural edit, not a content revision, so it writes
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

    character_ref_by_name: dict[str, tuple[str | None, str | None]] = {}
    for name, ref_id, look_id in character_links:
        if ref_id:
            card = characters_service.get_character(session, user_id=user_id, character_id=ref_id)
            _require_variant(card.skill, look_id, field="characters.look_id")
        character_ref_by_name[name] = (ref_id, look_id if ref_id else None)
    scene_ref_by_heading: dict[str, tuple[str | None, str | None]] = {}
    for heading, ref_id, variant_id in scene_links:
        if ref_id:
            scene_card = scenes_service.get_scene(session, user_id=user_id, scene_id=ref_id)
            _require_variant(scene_card.skill, variant_id, field="scenes.variant_id")
        scene_ref_by_heading[heading] = (ref_id, variant_id if ref_id else None)
    prop_ref_by_name: dict[str, str | None] = {}
    for name, ref_id in prop_links or []:
        if ref_id:
            props_service.get_prop(session, user_id=user_id, prop_id=ref_id)
        prop_ref_by_name[name.strip()] = ref_id

    next_characters = []
    for item in script.get("characters") or []:
        item = dict(item)
        if item.get("name") in character_ref_by_name:
            item["character_ref_id"], item["look_id"] = character_ref_by_name[item["name"]]
        next_characters.append(item)

    next_scenes = []
    for scene in script.get("scenes") or []:
        scene = dict(scene)
        if scene.get("heading") in scene_ref_by_heading:
            scene["ref_id"], scene["variant_id"] = scene_ref_by_heading[scene["heading"]]
        next_scenes.append(scene)

    next_props = link_props(script.get("props") or [], prop_ref_by_name)

    # A fresh dict, not a mutated nested one — SQLAlchemy only detects a
    # JSONB column change on reassignment, matching how every other turn
    # here writes `episode.script_json` (see `stream_new_script`/`stream_turn`).
    episode.script_json = {
        **script,
        "characters": next_characters,
        "scenes": next_scenes,
        "props": next_props,
    }
    session.flush()
    return episode


def link_props(
    props: list[dict[str, Any]],
    ref_by_name: dict[str, str | None],
    *,
    descriptions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """`props` with each named prop's link set; a linked name the script has
    no prop for yet is appended (the script only learns its props from a
    breakdown or a link). Over `copywriter.MAX_PROPS` is a 422."""
    descriptions = descriptions or {}
    next_props = [dict(item) for item in props if isinstance(item, dict)]
    known = {str(item.get("name")): item for item in next_props}
    for name, ref_id in ref_by_name.items():
        item = known.get(name)
        if item is None:
            if not ref_id and name not in descriptions:
                continue
            item = {"name": name, "description": "", "prop_ref_id": None}
            next_props.append(item)
            known[name] = item
        item["prop_ref_id"] = ref_id
        if descriptions.get(name) and not item.get("description"):
            item["description"] = descriptions[name]
    if len(next_props) > copywriter.MAX_PROPS:
        raise ValidationFailed(
            f"一个剧本最多关联 {copywriter.MAX_PROPS} 个道具。", fields={"props": "数量超限"}
        )
    return copywriter.sanitize_props(next_props)


def update_content(
    session: Session, *, user_id: str, episode_id: str, script: dict[str, Any]
) -> DramaEpisode:
    """Persists a user's direct hand-edit of the script text (title, logline,
    character traits, block text) straight to `episode.script_json` — same
    non-LLM write path as `update_links`, and for the same reason: this is a
    manual content edit the user made by typing, not a revision described in
    words, so it must not spend a model call or create a new `EpisodeScriptTurn`.

    Takes the *entire* document (not a per-field patch) and re-validates it
    through `copywriter._sanitize_script`, the same bounds/shape checks
    applied to every LLM-produced or client-echoed script — this is the one
    write path where arbitrary caller-supplied text lands directly in
    storage, so it must not skip that validation. `_sanitize_script` already
    preserves whatever `character_ref_id`/`ref_id` the caller sends back
    (see its docstring), so links set via `update_links` survive a content
    edit untouched.
    """
    _require_script_studio(session, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    if not episode.script_json:
        raise ValidationFailed("该剧本还没有初稿，请先生成初稿。")

    sanitized = copywriter._sanitize_script(script)
    if sanitized is None:
        raise ValidationFailed("剧本内容不能为空。")

    episode.script_json = sanitized
    session.flush()
    return episode


def _require_variant(skill: Any, variant_id: str | None, *, field: str) -> None:
    """A linked look / scene variant must belong to the linked card."""
    if variant_id and asset_variants_service.find_variant(skill, variant_id) is None:
        raise ValidationFailed("所选造型/变体不属于该卡片。", fields={field: "variant_id 无效"})
