"""Character looks (`/characters/{id}/looks…`) and scene variants
(`/scenes/{id}/variants…`), plus their images (`…/entries/{entry_id}`).

Owner-only, like the rest of the character/scene library: a missing or
someone else's card, look or image is a 404. Every write is a content edit,
so a published card drops back to draft (`withdraw_after_edit`, CL
invariant 3). Both card kinds share one implementation; `_register` mounts
it under each prefix with its own operation ids.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, rate_limited
from app.api.schemas.asset_variants import (
    AssetEntryCreateRequest,
    AssetEntryUpdateRequest,
    AssetEntryView,
    AssetVariantCreateRequest,
    AssetVariantUpdateRequest,
    AssetVariantView,
)
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.characters import voices as voices_service
from app.domain.errors import NotFound
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.models import CreationSkill, SkillAssetEntry, SkillAssetVariant
from app.presenters import asset_variants as presenter

router = APIRouter(tags=["asset-variants"])

Write = Annotated[None, Depends(rate_limited("authenticated_write"))]


def _character(session: Session, user_id: str, card_id: str) -> CreationSkill:
    return characters_service.get_character(session, user_id=user_id, character_id=card_id).skill


def _scene(session: Session, user_id: str, card_id: str) -> CreationSkill:
    return scenes_service.get_scene(session, user_id=user_id, scene_id=card_id).skill


def _variant(skill: CreationSkill, variant_id: str) -> SkillAssetVariant:
    variant = av.find_variant(skill, variant_id)
    if variant is None:
        raise NotFound("造型/变体不存在。")
    return variant


def _entry(skill: CreationSkill, entry_id: str) -> SkillAssetEntry:
    entry = av.find_entry(skill, entry_id)
    if entry is None:
        raise NotFound("参考图不存在。")
    return entry


def _presets(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    return payload.model_dump(exclude_none=True)


def _attributes(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    return payload.model_dump(exclude_none=True)


def _register(
    prefix: str, segment: str, load: Callable[[Session, str, str], CreationSkill]
) -> None:
    kind = prefix.rstrip("s")

    @router.post(
        f"/{prefix}/{{card_id}}/{segment}",
        response_model=AssetVariantView,
        status_code=201,
        operation_id=f"create_{kind}_{segment.rstrip('s')}",
    )
    def create_variant(
        card_id: str,
        payload: AssetVariantCreateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetVariantView:
        skill = load(session, user.id, card_id)
        variant = av.create_variant(
            session,
            skill,
            name=payload.name,
            description=payload.description,
            presets=_presets(payload.presets),
            attributes=_attributes(payload.attributes),
        )
        if payload.scene_id is not None:
            av.set_scene_link(
                session,
                skill,
                variant,
                scene_id=payload.scene_id,
                scene_variant_id=payload.scene_variant_id,
            )
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.variant_view(session, variant)

    @router.patch(
        f"/{prefix}/{{card_id}}/{segment}/{{variant_id}}",
        response_model=AssetVariantView,
        operation_id=f"update_{kind}_{segment.rstrip('s')}",
    )
    def update_variant(
        card_id: str,
        variant_id: str,
        payload: AssetVariantUpdateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetVariantView:
        skill = load(session, user.id, card_id)
        variant = av.update_variant(
            session,
            skill,
            _variant(skill, variant_id),
            name=payload.name,
            description=payload.description,
            presets=_presets(payload.presets),
            attributes=_attributes(payload.attributes),
            sort_order=payload.sort_order,
            make_default=payload.make_default,
        )
        if payload.clear_voice or payload.voice_id is not None:
            # Graph metadata, but harmless here: the edit already withdraws.
            voices_service.set_look_voice(
                session, skill, variant, None if payload.clear_voice else payload.voice_id
            )
        if payload.clear_scene or payload.scene_id is not None:
            av.set_scene_link(
                session,
                skill,
                variant,
                scene_id=None if payload.clear_scene else payload.scene_id,
                scene_variant_id=payload.scene_variant_id,
            )
            session.flush()
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.variant_view(session, variant)

    @router.delete(
        f"/{prefix}/{{card_id}}/{segment}/{{variant_id}}",
        status_code=204,
        operation_id=f"delete_{kind}_{segment.rstrip('s')}",
    )
    def delete_variant(
        card_id: str, variant_id: str, user: CurrentUser, session: DbSession, _: Write
    ) -> Response:
        skill = load(session, user.id, card_id)
        av.delete_variant(session, skill, _variant(skill, variant_id))
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return Response(status_code=204)

    @router.post(
        f"/{prefix}/{{card_id}}/{segment}/{{variant_id}}/entries",
        response_model=AssetEntryView,
        status_code=201,
        operation_id=f"add_{kind}_{segment.rstrip('s')}_entry",
    )
    def add_entry(
        card_id: str,
        variant_id: str,
        payload: AssetEntryCreateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetEntryView:
        skill = load(session, user.id, card_id)
        variant = _variant(skill, variant_id)
        av.require_owned_media(session, user_id=user.id, asset_id=payload.asset_id)
        entry = av.add_entry(
            session,
            skill,
            variant,
            asset_id=payload.asset_id,
            entry_type=payload.entry_type.value,
            view=av.check_view(skill, payload.view),
            label=payload.label,
            expressions=[str(e) for e in payload.expressions] if payload.expressions else None,
            camera=payload.camera.model_dump() if payload.camera else None,
        )
        # An upload is approved at once, so it can be the card's first anchor
        # — without one a scene's matrix cells have no master to keep.
        av.claim_anchor(session, skill, entry)
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.entry_view(session, entry)

    @router.patch(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}",
        response_model=AssetEntryView,
        operation_id=f"update_{kind}_entry",
    )
    def update_entry(
        card_id: str,
        entry_id: str,
        payload: AssetEntryUpdateRequest,
        user: CurrentUser,
        session: DbSession,
        _: Write,
    ) -> AssetEntryView:
        skill = load(session, user.id, card_id)
        entry = av.update_entry(
            session,
            skill,
            _entry(skill, entry_id),
            variant=_variant(skill, payload.variant_id) if payload.variant_id else None,
            entry_type=payload.entry_type.value if payload.entry_type else None,
            view=payload.view,
            clear_view=payload.clear_view,
            camera=payload.camera.model_dump() if payload.camera else None,
            clear_camera=payload.clear_camera,
            label=payload.label,
            expressions=[str(e) for e in payload.expressions]
            if payload.expressions is not None
            else None,
            status=payload.status.value if payload.status else None,
        )
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.entry_view(session, entry)

    @router.delete(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}",
        status_code=204,
        operation_id=f"delete_{kind}_entry",
    )
    def delete_entry(
        card_id: str, entry_id: str, user: CurrentUser, session: DbSession, _: Write
    ) -> Response:
        skill = load(session, user.id, card_id)
        av.remove_entry(session, skill, _entry(skill, entry_id))
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return Response(status_code=204)

    @router.post(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}:anchor",
        response_model=AssetEntryView,
        operation_id=f"set_{kind}_anchor",
    )
    def set_anchor(
        card_id: str, entry_id: str, user: CurrentUser, session: DbSession, _: Write
    ) -> AssetEntryView:
        skill = load(session, user.id, card_id)
        entry = _entry(skill, entry_id)
        av.set_anchor(session, skill, entry)
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.entry_view(session, entry)

    @router.post(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}:approve",
        response_model=AssetEntryView,
        operation_id=f"approve_{kind}_entry",
    )
    def approve_entry(
        card_id: str, entry_id: str, user: CurrentUser, session: DbSession, _: Write
    ) -> AssetEntryView:
        """Makes a candidate its slot's approved image; the one it replaces
        becomes a candidate (and hands over the anchor if it held it)."""
        skill = load(session, user.id, card_id)
        entry = av.approve_entry(session, skill, _entry(skill, entry_id))
        skill_library_service.withdraw_after_edit(session, skill)
        session.commit()
        return presenter.entry_view(session, entry)


_register("characters", "looks", _character)
_register("scenes", "variants", _scene)
