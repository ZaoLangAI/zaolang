"""A card's management graph (P4): `GET /v1/{characters|scenes}/{id}/graph`
and the edge writes under `…/edges`.

Owner-only like the rest of the library (someone else's card, look, image or
edge is a 404). Edges are graph metadata, not published content: writing one
neither withdraws a published card nor goes through moderation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.asset_graph import (
    AssetEdgeCreateRequest,
    AssetEdgeUpdateRequest,
    AssetEdgeView,
    AssetGraphResponse,
)
from app.domain.asset_graph import service as graph_service
from app.domain.characters import service as characters_service
from app.domain.props import service as props_service
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill
from app.presenters import asset_graph as presenter

router = APIRouter(tags=["asset-graph"])

Write = Annotated[None, Depends(rate_limited("authenticated_write"))]
Read = Annotated[None, Depends(rate_limited("public_read"))]

# Loads an owned card: `(skill, full description, voice description)`.
Loader = Callable[[Session, str, str], tuple[CreationSkill, str | None, str | None]]


def _character(
    session: Session, user_id: str, card_id: str
) -> tuple[CreationSkill, str | None, str | None]:
    view = characters_service.get_character(session, user_id=user_id, character_id=card_id)
    return view.skill, view.description, view.voice_description


def _scene(
    session: Session, user_id: str, card_id: str
) -> tuple[CreationSkill, str | None, str | None]:
    view = scenes_service.get_scene(session, user_id=user_id, scene_id=card_id)
    return view.skill, view.description, None


def _prop(
    session: Session, user_id: str, card_id: str
) -> tuple[CreationSkill, str | None, str | None]:
    view = props_service.get_prop(session, user_id=user_id, prop_id=card_id)
    return view.skill, view.description, None


def _register(prefix: str, load: Loader) -> None:
    kind = prefix.rstrip("s")

    @router.get(
        f"/{prefix}/{{card_id}}/graph",
        response_model=AssetGraphResponse,
        operation_id=f"get_{kind}_graph",
    )
    def get_graph(
        card_id: str, user: CurrentUser, session: DbSession, _: Read
    ) -> AssetGraphResponse:
        skill, description, voice_description = load(session, user.id, card_id)
        return presenter.graph_response(
            session,
            graph_service.graph(session, skill),
            description=description,
            voice_description=voice_description,
        )

    @router.post(
        f"/{prefix}/{{card_id}}/edges",
        response_model=AssetEdgeView,
        status_code=201,
        operation_id=f"create_{kind}_edge",
    )
    def create_edge(
        card_id: str,
        payload: AssetEdgeCreateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetEdgeView:
        skill, _description, _voice = load(session, user.id, card_id)
        edge = graph_service.add_edge(
            session,
            skill,
            level=payload.level,
            source_id=payload.source_id,
            target_id=payload.target_id,
            relations=[str(r) for r in payload.relations],
            label=payload.label,
        )
        session.commit()
        return presenter.edge_view(edge)

    @router.patch(
        f"/{prefix}/{{card_id}}/edges/{{edge_id}}",
        response_model=AssetEdgeView,
        operation_id=f"update_{kind}_edge",
    )
    def update_edge(
        card_id: str,
        edge_id: str,
        payload: AssetEdgeUpdateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetEdgeView:
        skill, _description, _voice = load(session, user.id, card_id)
        edge = graph_service.update_edge(
            session,
            skill,
            graph_service.find_edge(session, skill, edge_id),
            relations=[str(r) for r in payload.relations] if payload.relations else None,
            label=payload.label,
            clear_label=payload.clear_label,
        )
        session.commit()
        return presenter.edge_view(edge)

    @router.delete(
        f"/{prefix}/{{card_id}}/edges/{{edge_id}}",
        status_code=204,
        operation_id=f"delete_{kind}_edge",
    )
    def delete_edge(
        card_id: str, edge_id: str, user: CurrentUser, session: DbSession, _: Write
    ) -> Response:
        skill, _description, _voice = load(session, user.id, card_id)
        graph_service.delete_edge(session, skill, graph_service.find_edge(session, skill, edge_id))
        session.commit()
        return Response(status_code=204)


_register("characters", _character)
_register("scenes", _scene)
_register("props", _prop)
