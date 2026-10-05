"""Character library: reusable cast members for generation and drama scripts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.characters import (
    CharacterActionClip,
    CharacterCreateRequest,
    CharacterDescribeRequest,
    CharacterDescribeResponse,
    CharacterPublishRequest,
    CharacterReferenceAsset,
    CharacterReferenceAssetUpdateRequest,
    CharacterResponse,
    CharacterScriptLinkView,
    CharacterUpdateRequest,
)
from app.domain.characters import script_context
from app.domain.characters import service as characters
from app.presenters import asset_variants as asset_variant_presenter
from app.presenters import media_urls

router = APIRouter(tags=["characters"])


@router.post("/characters", response_model=CharacterResponse, status_code=201)
def create_character(
    payload: CharacterCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.create_character(
        session,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
        voice_description=payload.voice_description,
    )
    session.commit()
    return _character_response(session, character)


@router.get("/characters", response_model=list[CharacterResponse])
def list_characters(
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[CharacterResponse]:
    return [
        _character_response(session, character)
        for character in characters.list_characters(session, user_id=user.id)
    ]


@router.get("/characters/{character_id}", response_model=CharacterResponse)
def get_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> CharacterResponse:
    character = characters.get_character(session, user_id=user.id, character_id=character_id)
    return _character_response(session, character)


@router.get("/characters/{character_id}/script-links", response_model=list[CharacterScriptLinkView])
def list_character_script_links(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[CharacterScriptLinkView]:
    """Scripts that link this card — what 「AI 生成」 can draft from."""
    characters.get_character(session, user_id=user.id, character_id=character_id)
    return [
        CharacterScriptLinkView(
            episode_id=link.episode_id,
            episode_title=link.episode_title,
            series_title=link.series_title,
            character_name=link.character_name,
            look_id=link.look_id,
            dialogue_count=len(link.dialogue_lines),
        )
        for link in script_context.linked_scripts(
            session, user_id=user.id, character_id=character_id
        )
    ]


@router.post("/characters/{character_id}/describe", response_model=CharacterDescribeResponse)
def describe_character(
    character_id: str,
    payload: CharacterDescribeRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("script_studio_write"))],
) -> CharacterDescribeResponse:
    """Drafts the description / voice description from the linked scripts.
    Saves nothing: the draft goes back to the edit form for the author."""
    draft, links = script_context.draft_profile(
        session,
        user_id=user.id,
        character_id=character_id,
        episode_id=payload.episode_id,
        fields=tuple(payload.fields),
    )
    # The agent run row is the only write; keep it for replay/audit.
    session.commit()
    return CharacterDescribeResponse(
        description=draft.description,
        voice_description=draft.voice_description,
        episode_ids=[link.episode_id for link in links],
    )


@router.patch("/characters/{character_id}", response_model=CharacterResponse)
def update_character(
    character_id: str,
    payload: CharacterUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.update_character(
        session,
        user_id=user.id,
        character_id=character_id,
        name=payload.name,
        description=payload.description,
        reference_asset_ids=payload.reference_asset_ids,
        voice_description=payload.voice_description,
    )
    session.commit()
    return _character_response(session, character)


@router.delete("/characters/{character_id}", status_code=204)
def delete_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> None:
    characters.delete_character(session, user_id=user.id, character_id=character_id)
    session.commit()


@router.patch(
    "/characters/{character_id}/reference-assets/{asset_id}", response_model=CharacterResponse
)
def update_character_reference_asset(
    character_id: str,
    asset_id: str,
    payload: CharacterReferenceAssetUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.update_reference_asset(
        session,
        user_id=user.id,
        character_id=character_id,
        asset_id=asset_id,
        view=payload.view.value if payload.view is not None else None,
        label=payload.label,
    )
    session.commit()
    return _character_response(session, character)


@router.delete(
    "/characters/{character_id}/reference-assets/{asset_id}", response_model=CharacterResponse
)
def delete_character_reference_asset(
    character_id: str,
    asset_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.remove_reference_asset(
        session, user_id=user.id, character_id=character_id, asset_id=asset_id
    )
    session.commit()
    return _character_response(session, character)


@router.post("/characters/{character_id}/publish", response_model=CharacterResponse)
def publish_character(
    character_id: str,
    payload: CharacterPublishRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.publish_character(
        session,
        user_id=user.id,
        character_id=character_id,
        portrait_consent=payload.portrait_consent,
    )
    session.commit()
    return _character_response(session, character)


@router.post("/characters/{character_id}/withdraw", response_model=CharacterResponse)
def withdraw_character(
    character_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CharacterResponse:
    character = characters.withdraw_character(session, user_id=user.id, character_id=character_id)
    session.commit()
    return _character_response(session, character)


def _character_response(session: Session, character: characters.CharacterView) -> CharacterResponse:
    return CharacterResponse(
        id=character.id,
        name=character.name,
        description=character.description,
        reference_assets=[
            CharacterReferenceAsset(
                asset_id=str(entry.get("asset_id")),
                view=str(entry.get("view") or "general"),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in character.reference_assets
            if entry.get("asset_id")
        ],
        action_clips=[
            CharacterActionClip(
                asset_id=str(entry.get("asset_id")),
                label=entry.get("label"),
                url=media_urls.asset_url(session, str(entry.get("asset_id"))),
                created_at=entry.get("created_at"),
            )
            for entry in character.action_clips
            if entry.get("asset_id")
        ],
        voice_description=character.voice_description,
        looks=asset_variant_presenter.variant_views(session, character.skill),
        anchor_entry_id=asset_variant_presenter.anchor_entry_id(character.skill),
        status=character.status,
        visibility=character.visibility,
        access_credits=character.access_credits,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )
