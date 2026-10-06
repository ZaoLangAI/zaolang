"""Prop library (道具, AC-4) — CRUD for reusable objects, mirroring
`scenes.py`. Images are managed through the shared variant routes
(`asset_variants.py`, `/v1/props/{id}/variants…`) and generated through
`asset_derive.py` / ordinary jobs with `asset_kind=prop`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.props import (
    PropCreateRequest,
    PropReferenceAsset,
    PropResponse,
    PropUpdateRequest,
)
from app.domain.props import service as props
from app.presenters import asset_variants as asset_variant_presenter
from app.presenters import media_urls

router = APIRouter(tags=["props"])

Write = Annotated[None, Depends(rate_limited("authenticated_write"))]
Read = Annotated[None, Depends(rate_limited("public_read"))]


@router.post("/props", response_model=PropResponse, status_code=201)
def create_prop(
    payload: PropCreateRequest, user: CurrentUser, session: DbSession, _: Write
) -> PropResponse:
    prop = props.create_prop(
        session,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
    )
    session.commit()
    return _prop_response(session, prop)


@router.get("/props", response_model=list[PropResponse])
def list_props(user: CurrentUser, session: DbSession, _: Read) -> list[PropResponse]:
    return [_prop_response(session, prop) for prop in props.list_props(session, user_id=user.id)]


@router.get("/props/{prop_id}", response_model=PropResponse)
def get_prop(prop_id: str, user: CurrentUser, session: DbSession, _: Read) -> PropResponse:
    return _prop_response(session, props.get_prop(session, user_id=user.id, prop_id=prop_id))


@router.patch("/props/{prop_id}", response_model=PropResponse)
def update_prop(
    prop_id: str, payload: PropUpdateRequest, user: CurrentUser, session: DbSession, _: Write
) -> PropResponse:
    prop = props.update_prop(
        session,
        user_id=user.id,
        prop_id=prop_id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
    )
    session.commit()
    return _prop_response(session, prop)


@router.delete("/props/{prop_id}", status_code=204)
def delete_prop(prop_id: str, user: CurrentUser, session: DbSession, _: Write) -> None:
    props.delete_prop(session, user_id=user.id, prop_id=prop_id)
    session.commit()


@router.post("/props/{prop_id}/publish", response_model=PropResponse)
def publish_prop(prop_id: str, user: CurrentUser, session: DbSession, _: Write) -> PropResponse:
    prop = props.publish_prop(session, user_id=user.id, prop_id=prop_id)
    session.commit()
    return _prop_response(session, prop)


@router.post("/props/{prop_id}/withdraw", response_model=PropResponse)
def withdraw_prop(prop_id: str, user: CurrentUser, session: DbSession, _: Write) -> PropResponse:
    prop = props.withdraw_prop(session, user_id=user.id, prop_id=prop_id)
    session.commit()
    return _prop_response(session, prop)


def _prop_response(session: Session, prop: props.PropView) -> PropResponse:
    return PropResponse(
        id=prop.id,
        name=prop.name,
        description=prop.description,
        reference_assets=[
            PropReferenceAsset(
                asset_id=str(entry.get("asset_id")),
                view=str(entry.get("view") or "general"),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in prop.reference_assets
            if entry.get("asset_id")
        ],
        variants=asset_variant_presenter.variant_views(session, prop.skill),
        anchor_entry_id=asset_variant_presenter.anchor_entry_id(prop.skill),
        status=prop.status,
        visibility=prop.visibility,
        access_credits=prop.access_credits,
        created_at=prop.created_at,
        updated_at=prop.updated_at,
    )
