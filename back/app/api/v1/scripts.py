"""Conversational script writing (文案创作) — streamed turns over SSE.

Each turn is a `POST` that responds with a `text/event-stream` body:
`event: start` (once, carries `episode_id` for a brand-new script),
`event: delta` (repeated, `{"text": str}` chunks as the model writes the
user-facing summary/script), `event: thinking` (repeated, `{"text": str}`
chunks of the model's live reasoning — best-effort: some providers stream it
token-by-token, others hand it back in one late burst, see
`llm_client.stream_complete`'s own docstring), `event: complete` (once, the
finished `{turn_id, turn_no, summary, script, degraded, thinking}`), or
`event: error` (`{"message": str}`) instead of `complete` when the turn
failed after streaming had already started — headers are long sent by then,
so an error can only be reported inside the stream, never as an HTTP status.
A bare SSE comment line (no `event:`/`data:`) may also appear before the
first real chunk, as a heartbeat; `parseSseFrame` on the frontend silently
skips it (no `data:` line), so it never reaches `ScriptStreamEvent` handling.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import queue
import threading
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.script import (
    ScriptContentUpdateRequest,
    ScriptCreateRequest,
    ScriptDetailResponse,
    ScriptDocument,
    ScriptLinksUpdateRequest,
    ScriptRetryRequest,
    ScriptSummaryResponse,
    ScriptTurnRequest,
    ScriptTurnSnapshotResponse,
    ScriptTurnSummary,
)
from app.db import session_scope
from app.domain.errors import DomainError
from app.domain.script_writing import service as script_writing_service
from app.llm.client import StreamChunk
from app.models import EpisodeScriptTurn

router = APIRouter(tags=["scripts"])

SCRIPTS_ENDPOINT = "POST /v1/scripts"
SCRIPT_TURNS_ENDPOINT = "POST /v1/scripts/{episode_id}/turns"
SCRIPT_RETRY_ENDPOINT = "POST /v1/scripts/{episode_id}/retry"

# How often a heartbeat comment is sent while nothing else is ready — keeps
# the connection carrying traffic during a long silent gap before the first
# real chunk (a cold proxy buffer, or a provider that hands reasoning back
# in one late burst rather than incrementally) instead of looking
# indistinguishable from a hung connection. This alone does not bound a
# genuinely stuck call — that ceiling is `llm_client
# .STREAM_WALL_CLOCK_TIMEOUT_SECONDS`, enforced inside the stream loop
# itself, not here.
_HEARTBEAT_INTERVAL_SECONDS = 12.0
_HEARTBEAT_COMMENT = ": heartbeat\n\n"
_HEARTBEAT = object()
_DRAIN_DONE = object()


def _with_heartbeat(source: Iterator[Any]) -> Iterator[Any]:
    """Drains `source` on a background thread, yielding `_HEARTBEAT` in
    between its items whenever none arrives within
    `_HEARTBEAT_INTERVAL_SECONDS`.

    `source` here is always one of `stream_new_script`/`stream_turn`'s own
    generators — draining it on a background thread also runs their
    trailing (non-yielding) finalize/DB-write code there, since a generator
    only finishes executing past its last `yield` once fully iterated; by
    the time this wrapper's own iterator ends, that write has already
    happened and the caller's `TurnResult` is fully populated, same as
    before this wrapper existed. Runs inside a copy of the calling context
    (`contextvars.copy_context()`) so request-scoped correlation ids
    (`app.observability.context`) still land on the `AgentRun` written at
    the end of that drain — a bare `threading.Thread` would otherwise start
    with an empty context.
    """
    ctx = contextvars.copy_context()
    q: queue.Queue[Any] = queue.Queue()
    errors: list[BaseException] = []

    def _drain() -> None:
        try:
            for item in source:
                q.put(item)
        except BaseException as exc:
            errors.append(exc)
        finally:
            q.put(_DRAIN_DONE)

    thread = threading.Thread(target=lambda: ctx.run(_drain), daemon=True)
    thread.start()
    while True:
        try:
            item = q.get(timeout=_HEARTBEAT_INTERVAL_SECONDS)
        except queue.Empty:
            yield _HEARTBEAT
            continue
        if item is _DRAIN_DONE:
            if errors:
                raise errors[0]
            return
        yield item


SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}
# Returning a `Response` subclass directly bypasses FastAPI's automatic
# serialization, so the route decorator's `status_code=202` never applies —
# every `StreamingResponse` below has to set it itself.
SSE_STATUS_CODE = 202


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _replay_stream(snapshot: dict[str, Any]) -> Iterator[str]:
    """A retried request with the same idempotency key never re-runs the LLM
    turn or creates a second episode/turn — it just replays the outcome as a
    single `complete` frame, with no `delta` frames in front of it."""
    yield _sse("complete", snapshot)


def _remember_idempotent(
    *, user_id: str, endpoint: str, key: str | None, request_hash: str, snapshot: dict[str, Any]
) -> None:
    if not key:
        return
    # A fresh session: by the time this runs (after the generator above has
    # streamed to completion) the request-scoped session from the route
    # function may already be closed — see the module docstring in
    # `app.domain.script_writing.service` for why. Concurrent conflicts are
    # suppressed: another request with the same key already won, nothing
    # further to persist here, and `remember` rolls back on conflict itself
    # before raising, so there is nothing left to clean up either.
    with session_scope() as record_session, contextlib.suppress(DomainError):
        idempotency.remember(
            record_session,
            user_id=user_id,
            endpoint=endpoint,
            key=key,
            request_hash=request_hash,
            status_code=202,
            response=snapshot,
        )


def _turn_sse_body(
    *,
    stream: Iterator[StreamChunk],
    result: script_writing_service.TurnResult,
    episode_id: str,
    endpoint: str,
    user_id: str,
    idempotency_key: str | None,
    request_hash: str,
) -> Iterator[str]:
    """Shared tail of every streamed-turn route below `event: start` (if
    any): drains `stream` (heartbeat-wrapped), then emits `complete`/`error`
    and records the idempotency snapshot — identical for a first draft, a
    revision turn, and a first-draft retry, so only what builds `stream`
    itself differs per route.
    """
    for chunk in _with_heartbeat(stream):
        if chunk is _HEARTBEAT:
            yield _HEARTBEAT_COMMENT
            continue
        assert isinstance(chunk, StreamChunk)
        event = "delta" if chunk.kind == "content" else "thinking"
        yield _sse(event, {"text": chunk.text})

    if result.error:
        yield _sse("error", {"message": result.error})
        return

    snapshot = {
        "episode_id": episode_id,
        "turn_id": result.turn_id,
        "turn_no": result.turn_no,
        "summary": result.summary,
        "script": result.script,
        "degraded": result.degraded,
        "thinking": result.thinking,
    }
    _remember_idempotent(
        user_id=user_id,
        endpoint=endpoint,
        key=idempotency_key,
        request_hash=request_hash,
        snapshot=snapshot,
    )
    yield _sse("complete", snapshot)


def _turn_summary(turn: EpisodeScriptTurn) -> ScriptTurnSummary:
    return ScriptTurnSummary(
        id=turn.id,
        turn_no=turn.turn_no,
        user_message=turn.user_message,
        summary=turn.summary,
        referenced_skill_ids=list(turn.referenced_skill_ids_json or []),
        created_at=turn.created_at,
        thinking=turn.thinking_text or "",
    )


@router.post("/scripts", status_code=202)
def create_script(
    payload: ScriptCreateRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> StreamingResponse:
    request_hash = idempotency.hash_request(payload.model_dump(mode="json"))
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=SCRIPTS_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return StreamingResponse(
                _replay_stream(replay.response_snapshot),
                status_code=SSE_STATUS_CODE,
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )

    prep = script_writing_service.prepare_new_script(
        session,
        user_id=user.id,
        title=payload.title,
        idea=payload.idea,
        referenced_skill_ids=payload.referenced_skill_ids,
        series_id=payload.series_id,
    )
    session.commit()

    result = script_writing_service.TurnResult()

    def generate() -> Iterator[str]:
        yield _sse("start", {"episode_id": prep.episode_id})
        yield from _turn_sse_body(
            stream=script_writing_service.stream_new_script(prep, user_id=user.id, result=result),
            result=result,
            episode_id=prep.episode_id,
            endpoint=SCRIPTS_ENDPOINT,
            user_id=user.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    return StreamingResponse(
        generate(), status_code=SSE_STATUS_CODE, media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/scripts/{episode_id}/retry", status_code=202)
def retry_script(
    episode_id: str,
    payload: ScriptRetryRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> StreamingResponse:
    """Re-runs the first draft for an episode shell whose original stream
    never finished (see `retry_new_script`'s docstring) — the empty-shell
    page's "重新生成初稿" action, offered in place of `POST /v1/scripts`
    precisely because that route always mints a new episode.
    """
    request_hash = idempotency.hash_request(
        {"episode_id": episode_id, **payload.model_dump(mode="json")}
    )
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=SCRIPT_RETRY_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return StreamingResponse(
                _replay_stream(replay.response_snapshot),
                status_code=SSE_STATUS_CODE,
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )

    prep = script_writing_service.retry_new_script(
        session,
        user_id=user.id,
        episode_id=episode_id,
        idea=payload.idea,
        referenced_skill_ids=payload.referenced_skill_ids,
    )
    session.commit()

    result = script_writing_service.TurnResult()

    def generate() -> Iterator[str]:
        yield _sse("start", {"episode_id": prep.episode_id})
        yield from _turn_sse_body(
            stream=script_writing_service.stream_new_script(prep, user_id=user.id, result=result),
            result=result,
            episode_id=prep.episode_id,
            endpoint=SCRIPT_RETRY_ENDPOINT,
            user_id=user.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    return StreamingResponse(
        generate(), status_code=SSE_STATUS_CODE, media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/scripts", response_model=list[ScriptSummaryResponse])
def list_scripts(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[ScriptSummaryResponse]:
    episodes = script_writing_service.list_scripts(session, user_id=user.id)
    responses: list[ScriptSummaryResponse] = []
    for episode in episodes:
        script = episode.script_json or {}
        turn_count = session.scalar(
            select(func.count(EpisodeScriptTurn.id)).where(
                EpisodeScriptTurn.episode_id == episode.id
            )
        )
        responses.append(
            ScriptSummaryResponse(
                episode_id=episode.id,
                title=episode.title,
                logline=str(script.get("logline") or ""),
                status=episode.status,
                turn_count=turn_count or 0,
                updated_at=episode.updated_at,
            )
        )
    return responses


@router.get("/scripts/{episode_id}", response_model=ScriptDetailResponse)
def get_script(
    episode_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> ScriptDetailResponse:
    episode, turns = script_writing_service.get_script(
        session, user_id=user.id, episode_id=episode_id
    )
    last_error = script_writing_service.script_last_error(session, episode_id=episode.id)
    # Persist a historical empty-shell backfill (`source_idea` recovered
    # from a nearby AgentRun) so the next retry can omit the idea body.
    # A clean read is a no-op commit.
    session.commit()
    return ScriptDetailResponse(
        episode_id=episode.id,
        series_id=episode.series_id,
        title=episode.title,
        status=episode.status,
        script=ScriptDocument.model_validate(episode.script_json or {}),
        turns=[_turn_summary(turn) for turn in turns],
        source_idea=episode.source_idea or "",
        source_referenced_skill_ids=list(episode.source_referenced_skill_ids_json or []),
        last_error=last_error,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
    )


@router.delete("/scripts/{episode_id}", status_code=204)
def delete_script(
    episode_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> None:
    script_writing_service.delete_script(session, user_id=user.id, episode_id=episode_id)
    session.commit()


@router.get(
    "/scripts/{episode_id}/turns/{turn_id}/snapshot",
    response_model=ScriptTurnSnapshotResponse,
)
def get_turn_snapshot(
    episode_id: str,
    turn_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> ScriptTurnSnapshotResponse:
    turn = script_writing_service.get_turn_snapshot(
        session, user_id=user.id, episode_id=episode_id, turn_id=turn_id
    )
    return ScriptTurnSnapshotResponse(
        turn_id=turn.id,
        turn_no=turn.turn_no,
        summary=turn.summary,
        script=ScriptDocument.model_validate(turn.script_snapshot_json or {}),
    )


@router.patch("/scripts/{episode_id}/links", response_model=ScriptDocument)
def update_script_links(
    episode_id: str,
    payload: ScriptLinksUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> ScriptDocument:
    """Links characters/scene headings to reusable `Character`/`Scene`
    assets. Unlike every other route in this file, this is a plain
    request/response — it is a structural edit, not a content revision, so
    it never touches the SSE turn machinery (see `update_links`'s docstring).
    """
    episode = script_writing_service.update_links(
        session,
        user_id=user.id,
        episode_id=episode_id,
        character_links=[(c.name, c.character_ref_id) for c in payload.characters],
        scene_links=[(s.heading, s.ref_id) for s in payload.scenes],
    )
    session.commit()
    return ScriptDocument.model_validate(episode.script_json or {})


@router.patch("/scripts/{episode_id}", response_model=ScriptDocument)
def update_script_content(
    episode_id: str,
    payload: ScriptContentUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> ScriptDocument:
    """Persists a user's direct hand-edit of the script text (title,
    logline, character traits, block text). Same shape as
    `update_script_links` above — a plain request/response, not the SSE turn
    machinery, since this is a manual edit rather than a model-driven
    revision.
    """
    episode = script_writing_service.update_content(
        session,
        user_id=user.id,
        episode_id=episode_id,
        script=payload.script.model_dump(mode="json"),
    )
    session.commit()
    return ScriptDocument.model_validate(episode.script_json or {})


@router.post("/scripts/{episode_id}/turns", status_code=202)
def create_turn(
    episode_id: str,
    payload: ScriptTurnRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> StreamingResponse:
    endpoint = SCRIPT_TURNS_ENDPOINT
    request_hash = idempotency.hash_request(
        {"episode_id": episode_id, **payload.model_dump(mode="json")}
    )
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=endpoint,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return StreamingResponse(
                _replay_stream(replay.response_snapshot),
                status_code=SSE_STATUS_CODE,
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )

    prep = script_writing_service.prepare_turn(
        session,
        user_id=user.id,
        episode_id=episode_id,
        message=payload.message,
        referenced_skill_ids=payload.referenced_skill_ids,
        client_script=(
            payload.current_script.model_dump(mode="json")
            if payload.current_script is not None
            else None
        ),
    )
    session.commit()

    result = script_writing_service.TurnResult()

    def generate() -> Iterator[str]:
        yield from _turn_sse_body(
            stream=script_writing_service.stream_turn(prep, user_id=user.id, result=result),
            result=result,
            episode_id=prep.episode_id,
            endpoint=endpoint,
            user_id=user.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    return StreamingResponse(
        generate(), status_code=SSE_STATUS_CODE, media_type="text/event-stream", headers=SSE_HEADERS
    )
