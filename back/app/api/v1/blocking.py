"""白膜 (3D blockout) studio routes, nested under a script episode.

Streamed routes follow `app.api.v1.scripts`' SSE contract, plus one event:
`event: phase` (`{"name": "route"|"script"|"blocking"}`) marks which of a
turn's up-to-three model calls the following `delta`/`thinking` frames
belong to. `complete` carries `{turn_id, turn_no, summary, script,
script_changed, blocking: BlockingState, degraded, thinking}`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.blocking import BlockingDocument, BlockingState, BlockingVersionResponse
from app.api.schemas.script import (
    BlockingPatchRequest,
    BlockingSettingsRequest,
    BlockingTurnRequest,
)
from app.api.v1.scripts import (
    _HEARTBEAT,
    _HEARTBEAT_COMMENT,
    SSE_HEADERS,
    SSE_STATUS_CODE,
    _remember_idempotent,
    _replay_stream,
    _sse,
    _with_heartbeat,
)
from app.db import session_scope
from app.domain.blocking import service as blocking_service
from app.llm.client import StreamChunk
from app.models import DramaEpisode

router = APIRouter(tags=["blocking"])

BLOCKING_TURNS_ENDPOINT = "POST /v1/scripts/{episode_id}/blocking/turns"
BLOCKING_REBUILD_ENDPOINT = "POST /v1/scripts/{episode_id}/blocking:rebuild"


def _state(session: DbSession, episode: DramaEpisode) -> BlockingState:
    return BlockingState.model_validate(blocking_service.get_state(session, episode=episode))


def _blocking_sse_body(
    *,
    stream: Iterator[StreamChunk | blocking_service.PhaseMarker],
    result: blocking_service.BlockingTurnResult,
    episode_id: str,
    endpoint: str,
    user_id: str,
    idempotency_key: str | None,
    request_hash: str,
) -> Iterator[str]:
    for chunk in _with_heartbeat(stream):
        if chunk is _HEARTBEAT:
            yield _HEARTBEAT_COMMENT
            continue
        if isinstance(chunk, blocking_service.PhaseMarker):
            yield _sse("phase", {"name": chunk.name})
            continue
        assert isinstance(chunk, StreamChunk)
        yield _sse("delta" if chunk.kind == "content" else "thinking", {"text": chunk.text})

    if result.error:
        yield _sse("error", {"message": result.error})
        return

    # The state is re-read in a fresh session: the persist window inside
    # the stream has committed by now, and staleness is computed server side.
    with session_scope() as session:
        episode = session.get(DramaEpisode, episode_id)
        state = (
            BlockingState.model_validate(blocking_service.get_state(session, episode=episode))
            if episode is not None
            else BlockingState()
        )
    if result.duration_warning:
        state.duration_warning = result.duration_warning
    snapshot = {
        "episode_id": episode_id,
        "turn_id": result.turn_id,
        "turn_no": result.turn_no,
        "summary": result.summary,
        "script": result.script,
        "script_changed": result.script_changed,
        "blocking": state.model_dump(mode="json"),
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


def _replay_or_none(
    session: DbSession, *, user_id: str, endpoint: str, key: str | None, request_hash: str
) -> StreamingResponse | None:
    if not key:
        return None
    replay = idempotency.find_replay(
        session, user_id=user_id, endpoint=endpoint, key=key, request_hash=request_hash
    )
    if replay is None:
        return None
    return StreamingResponse(
        _replay_stream(replay.response_snapshot),
        status_code=SSE_STATUS_CODE,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/scripts/{episode_id}/blocking/turns", status_code=202)
def create_blocking_turn(
    episode_id: str,
    payload: BlockingTurnRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> StreamingResponse:
    request_hash = idempotency.hash_request(
        {"episode_id": episode_id, **payload.model_dump(mode="json")}
    )
    replay = _replay_or_none(
        session,
        user_id=user.id,
        endpoint=BLOCKING_TURNS_ENDPOINT,
        key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    prep = blocking_service.prepare_blocking_turn(
        session,
        user_id=user.id,
        episode_id=episode_id,
        message=payload.message,
        client_script=(
            payload.current_script.model_dump(mode="json")
            if payload.current_script is not None
            else None
        ),
    )
    session.commit()
    result = blocking_service.BlockingTurnResult()

    def generate() -> Iterator[str]:
        yield from _blocking_sse_body(
            stream=blocking_service.stream_blocking_turn(prep, user_id=user.id, result=result),
            result=result,
            episode_id=prep.episode_id,
            endpoint=BLOCKING_TURNS_ENDPOINT,
            user_id=user.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    return StreamingResponse(
        generate(), status_code=SSE_STATUS_CODE, media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/scripts/{episode_id}/blocking:rebuild", status_code=202)
def rebuild_blocking(
    episode_id: str,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> StreamingResponse:
    """The first build, and the stale banner's "rebuild from the new
    script". Stages from the persisted script; no chat turn is written."""
    request_hash = idempotency.hash_request({"episode_id": episode_id, "rebuild": True})
    replay = _replay_or_none(
        session,
        user_id=user.id,
        endpoint=BLOCKING_REBUILD_ENDPOINT,
        key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    prep = blocking_service.prepare_rebuild(session, user_id=user.id, episode_id=episode_id)
    session.commit()
    result = blocking_service.BlockingTurnResult()

    def generate() -> Iterator[str]:
        yield from _blocking_sse_body(
            stream=blocking_service.stream_blocking_turn(prep, user_id=user.id, result=result),
            result=result,
            episode_id=prep.episode_id,
            endpoint=BLOCKING_REBUILD_ENDPOINT,
            user_id=user.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    return StreamingResponse(
        generate(), status_code=SSE_STATUS_CODE, media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.patch("/scripts/{episode_id}/blocking", response_model=BlockingState)
def patch_blocking(
    episode_id: str,
    payload: BlockingPatchRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> BlockingState:
    episode, _version = blocking_service.patch_manual(
        session,
        user_id=user.id,
        episode_id=episode_id,
        document=payload.document,
        base_version_no=payload.base_version_no,
    )
    state = _state(session, episode)
    session.commit()
    return state


@router.patch("/scripts/{episode_id}/blocking/settings", response_model=BlockingState)
def update_blocking_settings(
    episode_id: str,
    payload: BlockingSettingsRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> BlockingState:
    episode = blocking_service.update_settings(
        session,
        user_id=user.id,
        episode_id=episode_id,
        target_duration_seconds=payload.target_duration_seconds,
        aspect_ratio=payload.aspect_ratio,
        base_version_no=payload.base_version_no,
    )
    state = _state(session, episode)
    session.commit()
    return state


@router.get(
    "/scripts/{episode_id}/blocking/versions/{version_no}",
    response_model=BlockingVersionResponse,
)
def get_blocking_version(
    episode_id: str,
    version_no: int,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> BlockingVersionResponse:
    version = blocking_service.get_version(
        session, user_id=user.id, episode_id=episode_id, version_no=version_no
    )
    return BlockingVersionResponse(
        version_no=version.version_no,
        origin=version.origin,
        summary=version.summary,
        turn_id=version.turn_id,
        document=BlockingDocument.model_validate(version.blocking_json),
    )
