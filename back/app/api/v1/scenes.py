"""Scene library — CRUD for reusable settings, mirroring `characters.py`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.scenes import (
    SceneCreateRequest,
    SceneReferenceAsset,
    SceneReferenceAssetUpdateRequest,
    SceneResponse,
    SceneUpdateRequest,
)
from app.domain.scenes import service as scenes
from app.presenters import media_urls

router = APIRouter(tags=["scenes"])


@router.post("/scenes", response_model=SceneResponse, status_code=201)
def create_scene(
    payload: SceneCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.create_scene(
        session,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
    )
    session.commit()
    return _scene_response(session, scene)


@router.get("/scenes", response_model=list[SceneResponse])
def list_scenes(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[SceneResponse]:
    return [
        _scene_response(session, scene) for scene in scenes.list_scenes(session, user_id=user.id)
    ]


@router.get("/scenes/{scene_id}", response_model=SceneResponse)
def get_scene(
    scene_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> SceneResponse:
    scene = scenes.get_scene(session, user_id=user.id, scene_id=scene_id)
    return _scene_response(session, scene)


@router.patch("/scenes/{scene_id}", response_model=SceneResponse)
def update_scene(
    scene_id: str,
    payload: SceneUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.update_scene(
        session,
        user_id=user.id,
        scene_id=scene_id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
    )
    session.commit()
    return _scene_response(session, scene)


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(
    scene_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> None:
    scenes.delete_scene(session, user_id=user.id, scene_id=scene_id)
    session.commit()


@router.patch("/scenes/{scene_id}/reference-assets/{asset_id}", response_model=SceneResponse)
def update_scene_reference_asset(
    scene_id: str,
    asset_id: str,
    payload: SceneReferenceAssetUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.update_reference_asset(
        session,
        user_id=user.id,
        scene_id=scene_id,
        asset_id=asset_id,
        view=payload.view,
        label=payload.label,
    )
    session.commit()
    return _scene_response(session, scene)


@router.delete("/scenes/{scene_id}/reference-assets/{asset_id}", response_model=SceneResponse)
def delete_scene_reference_asset(
    scene_id: str,
    asset_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.remove_reference_asset(
        session, user_id=user.id, scene_id=scene_id, asset_id=asset_id
    )
    session.commit()
    return _scene_response(session, scene)


@router.post("/scenes/{scene_id}/publish", response_model=SceneResponse)
def publish_scene(
    scene_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.publish_scene(session, user_id=user.id, scene_id=scene_id)
    session.commit()
    return _scene_response(session, scene)


@router.post("/scenes/{scene_id}/withdraw", response_model=SceneResponse)
def withdraw_scene(
    scene_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> SceneResponse:
    scene = scenes.withdraw_scene(session, user_id=user.id, scene_id=scene_id)
    session.commit()
    return _scene_response(session, scene)


def _scene_response(session: Session, scene: scenes.SceneView) -> SceneResponse:
    return SceneResponse(
        id=scene.id,
        name=scene.name,
        description=scene.description,
        reference_assets=[
            SceneReferenceAsset(
                asset_id=str(entry.get("asset_id")),
                view=str(entry.get("view") or "general"),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in scene.reference_assets
            if entry.get("asset_id")
        ],
        status=scene.status,
        visibility=scene.visibility,
        access_credits=scene.access_credits,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )
