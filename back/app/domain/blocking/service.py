"""白膜 studio: build, revise and hand-edit an episode's blockout.

Same session-lifetime split as `app.domain.script_writing.service` (read its
module docstring): `prepare_*` validate against the request-scoped session,
the stream generator opens short `session_scope()` windows around each LLM
call and one more to persist, and no DB connection is held while a model
thinks.

A 白膜 chat turn runs up to three phases in one SSE stream:

1. `route` — `blocking_director.route_turn` decides whether the message
   also changes the script.
2. `script` — only when it does: the ordinary `copywriter.stream_revise_script`,
   so the script is only ever rewritten by one prompt.
3. `blocking` — `blocking_director.stream_derive_blocking` against the
   (possibly new) script.

The turn persists as one `EpisodeScriptTurn(origin="blocking")` — so the
文案 page's history shows it — plus one `EpisodeBlockingVersion`. A derive
that fails to parse never blanks the blockout: the sanitizer completes an
empty reply from the previous version, or from default staging.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import blocking_director, copywriter
from app.db import session_scope
from app.domain.blocking.sanitize import sanitize_blocking, stale_segment_keys
from app.domain.blocking.segments import default_target_duration, ordered_segments
from app.domain.blocking.vocabulary import ASPECT_RATIOS, TARGET_DURATION_MAX_SECONDS
from app.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.domain.script_writing import service as script_writing_service
from app.llm.client import StreamChunk
from app.models import DramaEpisode, EpisodeBlockingVersion, EpisodeScriptTurn
from app.platform_config import service as config_service

BLOCKING_STUDIO_FLAG = "blocking_studio_enabled"
MANUAL_COALESCE_WINDOW = dt.timedelta(seconds=60)
MAX_MESSAGE_LEN = script_writing_service.MAX_MESSAGE_LEN
REBUILD_MESSAGE = "按当前文案重建白膜"


def is_enabled(session: Session, *, user_id: str | None) -> bool:
    """Needs both flags: the 白膜 studio is a surface of script writing."""
    return config_service.is_enabled(
        session, script_writing_service.SCRIPT_STUDIO_FLAG, user_id=user_id
    ) and config_service.is_enabled(session, BLOCKING_STUDIO_FLAG, user_id=user_id)


def _require_blocking_studio(session: Session, *, user_id: str | None) -> None:
    if not is_enabled(session, user_id=user_id):
        raise NotFound("该功能暂未开放。")


def _episode_with_script(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    _require_blocking_studio(session, user_id=user_id)
    episode = script_writing_service._owned_episode(session, user_id=user_id, episode_id=episode_id)
    if not ordered_segments(episode.script_json or {}):
        raise ValidationFailed("该剧本还没有可以搭建白膜的内容，请先生成初稿。")
    return episode


def latest_version(session: Session, *, episode_id: str) -> EpisodeBlockingVersion | None:
    return session.scalar(
        select(EpisodeBlockingVersion)
        .where(EpisodeBlockingVersion.episode_id == episode_id)
        .order_by(EpisodeBlockingVersion.version_no.desc())
        .limit(1)
    )


def get_state(session: Session, *, episode: DramaEpisode) -> dict[str, Any]:
    """What `ScriptDetailResponse.blocking` carries. Staleness is computed
    here, server side, so there is exactly one hashing implementation."""
    script = episode.script_json or {}
    document = episode.blocking_json or None
    latest = latest_version(session, episode_id=episode.id)
    default_target = default_target_duration(script)
    target = episode.target_duration_seconds or default_target
    stale_keys = stale_segment_keys(document, script) if document else []
    warning: str | None = None
    if document:
        total = sum(int(s.get("duration_s") or 0) for s in document.get("segments") or [])
        if total and abs(total - target) >= 1:
            warning = f"当前白膜总时长 {total} 秒，与目标 {target} 秒不一致。"
    return {
        "document": document,
        "version_no": latest.version_no if latest else 0,
        "stale": bool(document) and bool(stale_keys),
        "stale_segment_keys": stale_keys,
        "duration_warning": warning,
        "target_duration_seconds": episode.target_duration_seconds,
        "default_target_duration_seconds": default_target,
    }


# --------------------------------------------------------------------------
# Streamed turns
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseMarker:
    """Yielded between `StreamChunk`s so the SSE layer can emit
    `event: phase` — the frontend labels the live preview with it."""

    name: str


@dataclass(slots=True)
class BlockingTurnPrep:
    episode_id: str
    message: str
    current_script: dict[str, Any]
    previous_blocking: dict[str, Any] | None
    target_duration_s: int | None
    next_turn_no: int
    parent_turn_id: str | None
    rebuild: bool = False


@dataclass(slots=True)
class BlockingTurnResult:
    turn_id: str | None = None
    turn_no: int = 0
    summary: str = ""
    script: dict[str, Any] = field(default_factory=dict)
    script_changed: bool = False
    blocking: dict[str, Any] = field(default_factory=dict)
    version_no: int = 0
    duration_warning: str | None = None
    degraded: bool = False
    thinking: str = ""
    error: str | None = None


def _next_turn(session: Session, episode_id: str) -> tuple[int, str | None]:
    last_turn = session.scalar(
        select(EpisodeScriptTurn)
        .where(EpisodeScriptTurn.episode_id == episode_id)
        .order_by(EpisodeScriptTurn.turn_no.desc())
        .limit(1)
    )
    return ((last_turn.turn_no + 1) if last_turn else 1, last_turn.id if last_turn else None)


def prepare_blocking_turn(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    message: str,
    client_script: dict[str, Any] | None = None,
) -> BlockingTurnPrep:
    episode = _episode_with_script(session, user_id=user_id, episode_id=episode_id)
    message = message.strip()[:MAX_MESSAGE_LEN]
    if not message:
        raise ValidationFailed("请描述你想要的调整。")
    current_script = (
        copywriter._sanitize_script(client_script) if client_script is not None else None
    ) or episode.script_json
    next_turn_no, parent_turn_id = _next_turn(session, episode.id)
    return BlockingTurnPrep(
        episode_id=episode.id,
        message=message,
        current_script=current_script,
        previous_blocking=episode.blocking_json or None,
        target_duration_s=episode.target_duration_seconds,
        next_turn_no=next_turn_no,
        parent_turn_id=parent_turn_id,
    )


def prepare_rebuild(session: Session, *, user_id: str, episode_id: str) -> BlockingTurnPrep:
    """(Re)stages the blockout from the current script — the first build,
    and the stale banner's "rebuild" action. No chat turn is written."""
    episode = _episode_with_script(session, user_id=user_id, episode_id=episode_id)
    return BlockingTurnPrep(
        episode_id=episode.id,
        message=REBUILD_MESSAGE,
        current_script=episode.script_json,
        previous_blocking=episode.blocking_json or None,
        target_duration_s=episode.target_duration_seconds,
        next_turn_no=0,
        parent_turn_id=None,
        rebuild=True,
    )


def stream_blocking_turn(
    prep: BlockingTurnPrep, *, user_id: str, result: BlockingTurnResult
) -> Iterator[StreamChunk | PhaseMarker]:
    script = prep.current_script
    script_changed = False
    summaries: list[str] = []
    thinking: list[str] = []
    degraded = False
    instruction = ""
    try:
        if not prep.rebuild:
            yield PhaseMarker("route")
            with session_scope() as session:
                route = blocking_director.route_turn(
                    session, message=prep.message, script=script, user_id=user_id
                )
            degraded = degraded or route.degraded
            instruction = route.blocking_instruction
            if route.touches_script:
                yield PhaseMarker("script")
                with session_scope() as session:
                    script_chunks, finalize_script = copywriter.stream_revise_script(
                        session,
                        message=route.script_instruction,
                        current_script=script,
                        user_id=user_id,
                    )
                yield from script_chunks
                with session_scope() as session:
                    script_outcome = finalize_script(session)
                degraded = degraded or script_outcome.degraded or not script_outcome.parse_ok
                if script_outcome.parse_ok:
                    script_changed = script_outcome.script != script
                    script = script_outcome.script
                if script_outcome.summary:
                    summaries.append(script_outcome.summary)
                if script_outcome.thinking:
                    thinking.append(script_outcome.thinking)
            elif not instruction:
                instruction = prep.message

        yield PhaseMarker("blocking")
        previous = prep.previous_blocking
        changed_keys = (
            stale_segment_keys(previous, script)
            if previous
            else [segment.key for segment in ordered_segments(script)]
        )
        target = prep.target_duration_s or default_target_duration(script)
        with session_scope() as session:
            blocking_chunks, finalize_blocking = blocking_director.stream_derive_blocking(
                session,
                instruction=instruction,
                script=script,
                previous=previous,
                changed_keys=changed_keys,
                target_duration_s=target,
                user_id=user_id,
            )
        yield from blocking_chunks
    except DomainError as exc:
        result.error = exc.message
        return
    except Exception as exc:
        result.error = str(exc)
        return

    with session_scope() as session:
        try:
            outcome = finalize_blocking(session)
            episode = session.get(DramaEpisode, prep.episode_id)
            if episode is None:
                raise NotFound("剧本不存在。")
            degraded = degraded or outcome.degraded or outcome.raw is None
            if outcome.summary:
                summaries.append(outcome.summary)
            if outcome.thinking:
                thinking.append(outcome.thinking)
            sanitized = sanitize_blocking(
                outcome.raw or {},
                script=script,
                target_duration_s=episode.target_duration_seconds,
                previous=prep.previous_blocking,
                mode="llm",
            )
            summary = "\n".join(summaries)[: copywriter.MAX_SUMMARY_LEN * 2]
            thinking_text = "\n\n".join(thinking)[: copywriter.MAX_THINKING_LEN]

            turn: EpisodeScriptTurn | None = None
            if not prep.rebuild:
                turn = EpisodeScriptTurn(
                    episode_id=prep.episode_id,
                    turn_no=prep.next_turn_no,
                    parent_turn_id=prep.parent_turn_id,
                    user_id=user_id,
                    user_message=prep.message,
                    summary=summary,
                    script_snapshot_json=script,
                    referenced_skill_ids_json=[],
                    agent_run_id=outcome.agent_run_id,
                    thinking_text=thinking_text,
                    origin="blocking",
                )
                session.add(turn)
            if script_changed:
                episode.script_json = script
            session.flush()

            version = _append_version(
                session,
                episode=episode,
                document=sanitized.document,
                origin="rebuild" if prep.rebuild else "llm_turn",
                user_id=user_id,
                summary=summary,
                turn_id=turn.id if turn else None,
                agent_run_id=outcome.agent_run_id,
            )

            result.turn_id = turn.id if turn else None
            result.turn_no = turn.turn_no if turn else 0
            result.summary = summary
            result.script = script
            result.script_changed = script_changed
            result.blocking = sanitized.document
            result.version_no = version.version_no
            result.duration_warning = sanitized.duration_warning
            result.degraded = degraded
            result.thinking = thinking_text
        except DomainError as exc:
            session.rollback()
            result.error = exc.message
        except Exception as exc:
            session.rollback()
            result.error = str(exc)


def _append_version(
    session: Session,
    *,
    episode: DramaEpisode,
    document: dict[str, Any],
    origin: str,
    user_id: str | None,
    summary: str = "",
    turn_id: str | None = None,
    agent_run_id: str | None = None,
) -> EpisodeBlockingVersion:
    latest = latest_version(session, episode_id=episode.id)
    version = EpisodeBlockingVersion(
        episode_id=episode.id,
        version_no=(latest.version_no + 1) if latest else 1,
        origin=origin,
        turn_id=turn_id,
        user_id=user_id,
        summary=summary,
        blocking_json=document,
        script_hash=str(document.get("script_hash") or ""),
        agent_run_id=agent_run_id,
    )
    session.add(version)
    episode.blocking_json = document
    session.flush()
    return version


# --------------------------------------------------------------------------
# Manual edits
# --------------------------------------------------------------------------


def _save_manual(
    session: Session,
    *,
    episode: DramaEpisode,
    document: dict[str, Any],
    user_id: str,
    base_version_no: int,
) -> EpisodeBlockingVersion:
    latest = latest_version(session, episode_id=episode.id)
    current_no = latest.version_no if latest else 0
    if base_version_no != current_no:
        raise Conflict(
            "白膜已在其他地方更新，请刷新后重试。",
            current_version_no=current_no,
        )
    now = dt.datetime.now(dt.UTC)
    if (
        latest is not None
        and latest.origin == "manual"
        and latest.user_id == user_id
        and latest.updated_at is not None
        and now - latest.updated_at < MANUAL_COALESCE_WINDOW
    ):
        latest.blocking_json = document
        latest.script_hash = str(document.get("script_hash") or "")
        latest.updated_at = now
        episode.blocking_json = document
        session.flush()
        return latest
    return _append_version(
        session, episode=episode, document=document, origin="manual", user_id=user_id
    )


def patch_manual(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    document: dict[str, Any],
    base_version_no: int,
) -> tuple[DramaEpisode, EpisodeBlockingVersion]:
    """A drag, a preset pick, a lens change — applied in the browser first,
    persisted here without a model call. Optimistic concurrency on
    `base_version_no`: a stale tab gets a 409 instead of silently
    overwriting a newer chat turn."""
    episode = _episode_with_script(session, user_id=user_id, episode_id=episode_id)
    if not episode.blocking_json:
        raise ValidationFailed("还没有白膜，请先生成白膜。")
    sanitized = sanitize_blocking(
        document,
        script=episode.script_json,
        target_duration_s=episode.target_duration_seconds,
        previous=episode.blocking_json,
        mode="manual",
    )
    version = _save_manual(
        session,
        episode=episode,
        document=sanitized.document,
        user_id=user_id,
        base_version_no=base_version_no,
    )
    return episode, version


def update_settings(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    target_duration_seconds: int | None,
    aspect_ratio: str | None,
    base_version_no: int,
) -> DramaEpisode:
    """Target runtime and aspect ratio. Re-fits the existing blockout's
    durations deterministically — no model call."""
    episode = _episode_with_script(session, user_id=user_id, episode_id=episode_id)
    if target_duration_seconds is not None and not (
        1 <= target_duration_seconds <= TARGET_DURATION_MAX_SECONDS
    ):
        raise ValidationFailed("目标总时长超出范围。")
    if aspect_ratio is not None and aspect_ratio not in ASPECT_RATIOS:
        raise ValidationFailed("不支持的画幅比例。")
    episode.target_duration_seconds = target_duration_seconds
    if episode.blocking_json:
        document = dict(episode.blocking_json)
        if aspect_ratio is not None:
            document["aspect_ratio"] = aspect_ratio
        sanitized = sanitize_blocking(
            document,
            script=episode.script_json,
            target_duration_s=target_duration_seconds,
            previous=episode.blocking_json,
            mode="manual",
        )
        _save_manual(
            session,
            episode=episode,
            document=sanitized.document,
            user_id=user_id,
            base_version_no=base_version_no,
        )
    session.flush()
    return episode


def get_version(
    session: Session, *, user_id: str, episode_id: str, version_no: int
) -> EpisodeBlockingVersion:
    _require_blocking_studio(session, user_id=user_id)
    episode = script_writing_service._owned_episode(session, user_id=user_id, episode_id=episode_id)
    version = session.scalar(
        select(EpisodeBlockingVersion).where(
            EpisodeBlockingVersion.episode_id == episode.id,
            EpisodeBlockingVersion.version_no == version_no,
        )
    )
    if version is None:
        raise NotFound("该白膜版本不存在。")
    return version
