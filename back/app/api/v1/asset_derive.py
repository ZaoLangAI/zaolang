"""调整修改 / 派生新属性图 in the management page (P6), and 多机位 (AC-2):

- `POST /v1/{characters|scenes}/{id}/entries/{entry_id}:adjust`
- `POST /v1/{characters|scenes}/{id}/entries/{entry_id}:derive`
- `POST /v1/{characters|scenes}/{id}/entries/{entry_id}:orbit` — one
  `image_to_image` job, one pass and one image per camera pose
  (`derive.plan_orbit`), priced per image.

`dry_run` (the default) prices one image like `quote:batch` (balance and
monthly cap) and, for a derive, previews the look-level relations. A submit
refuses up front when it does not fit, then — in one transaction — creates
the new look (when asked), its auto edge from the source look, and the job
(the ordinary submit: quote, reserve, commit, enqueue). The job's
idempotency key is derived from the request's and the source / target, and
a replay returns the first job without creating the look again. Only a
submit counts against `generation_submit`.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import rate_limit
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, client_identity, rate_limited
from app.api.schemas.asset_graph import (
    AssetAdjustRequest,
    AssetDeriveRequest,
    AssetGenerateResponse,
    AssetOrbitRequest,
)
from app.api.schemas.asset_variants import CameraPose
from app.api.schemas.jobs import GenerationParams
from app.domain.asset_graph import derive
from app.domain.asset_graph import service as graph_service
from app.domain.asset_variants import service as av
from app.domain.credits import service as credits_service
from app.domain.errors import InsufficientCredits, SpendLimitExceeded
from app.domain.image_assets import camera as camera_vocab
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import service as jobs_service
from app.domain.skill_library import service as skill_library_service
from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import AssetGraphLevel, AssetRelation, Operation

router = APIRouter(tags=["asset-graph"])

Write = Annotated[None, Depends(rate_limited("authenticated_write"))]


def _quote(
    session: Session,
    user_id: str,
    quality_tier: str,
    output_count: int = 1,
    operation: Operation = Operation.TEXT_TO_IMAGE,
) -> tuple[int, int, int | None, bool]:
    credits = jobs_service.quote_for(
        session,
        operation=operation,
        quality_tier=quality_tier,
        output_count=output_count,
    ).credits
    account = credits_service.get_or_create_account(session, user_id)
    remaining = credits_service.remaining_monthly_spend(account)
    return credits, account.available_balance, remaining, remaining is None or remaining >= credits


def _check_funds(credits: int, available: int, remaining: int | None, within: bool) -> None:
    if available < credits:
        raise InsufficientCredits(
            f"需要 {credits} 积分，当前可用 {available}。", required=credits, available=available
        )
    if not within:
        raise SpendLimitExceeded(
            f"需要 {credits} 积分，本月消费上限还剩 {remaining}。",
            required=credits,
            remaining=remaining,
        )


def _job_key(idempotency_key: str | None, *parts: str) -> str:
    token = hashlib.sha1(":".join(parts).encode()).hexdigest()[:12]
    return f"{(idempotency_key or new_id('idk'))[:100]}:{token}"


def _replay(session: Session, user_id: str, key: str) -> GenerationJob | None:
    return session.scalar(
        select(GenerationJob).where(
            GenerationJob.user_id == user_id, GenerationJob.idempotency_key == key
        )
    )


def _replayed_response(
    session: Session, user_id: str, quality_tier: str, job: GenerationJob
) -> AssetGenerateResponse:
    poses = job.request_json.get("camera_poses") or []
    credits, available, remaining, within = _quote(
        session,
        user_id,
        quality_tier,
        max(1, len(poses)),
        Operation.IMAGE_TO_IMAGE if poses else Operation.TEXT_TO_IMAGE,
    )
    return AssetGenerateResponse(
        credits=credits,
        available_credits=available,
        period_remaining=remaining,
        within_spend_limit=within,
        sufficient=available >= credits and within,
        job_id=job.id,
        variant_id=job.request_json.get("target_variant_id"),
        replayed=True,
        poses=[CameraPose.model_validate(pose) for pose in poses],
    )


def _submit(
    session: Session,
    *,
    request: Request,
    user: User,
    quality_tier: str,
    params: dict[str, Any],
    key: str,
    operation: Operation = Operation.TEXT_TO_IMAGE,
) -> GenerationJob:
    rate_limit.enforce("generation_submit", client_identity(request, user))
    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=operation,
        quality_tier=quality_tier,
        params=GenerationParams.model_validate(params).model_dump(),
        idempotency_key=key,
    )
    session.commit()
    if not result.replayed:
        job_dispatch.enqueue_or_fail(session, result.job)
    return result.job


def _register(prefix: str) -> None:
    kind = prefix.rstrip("s")

    @router.post(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}:adjust",
        response_model=AssetGenerateResponse,
        operation_id=f"adjust_{kind}_entry",
    )
    def adjust_entry(
        card_id: str,
        entry_id: str,
        payload: AssetAdjustRequest,
        request: Request,
        user: CurrentUser,
        session: DbSession,
        idempotency_key: IdempotencyKey,
        _: Write,
    ) -> AssetGenerateResponse:
        key = _job_key(idempotency_key, "adjust", entry_id, payload.instruction)
        if not payload.dry_run:
            replayed = _replay(session, user.id, key)
            if replayed is not None:
                return _replayed_response(session, user.id, payload.quality_tier, replayed)
        plan = derive.plan_adjust(
            session,
            user_id=user.id,
            kind=kind,
            card_id=card_id,
            entry_id=entry_id,
            instruction=payload.instruction,
            aspect_ratio=payload.aspect_ratio,
        )
        credits, available, remaining, within = _quote(session, user.id, payload.quality_tier)
        response = AssetGenerateResponse(
            credits=credits,
            available_credits=available,
            period_remaining=remaining,
            within_spend_limit=within,
            sufficient=available >= credits and within,
        )
        if payload.dry_run:
            return response
        _check_funds(credits, available, remaining, within)
        job = _submit(
            session,
            request=request,
            user=user,
            quality_tier=payload.quality_tier,
            params=plan.params,
            key=key,
        )
        return response.model_copy(update={"job_id": job.id, "variant_id": plan.source.variant_id})

    @router.post(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}:derive",
        response_model=AssetGenerateResponse,
        operation_id=f"derive_{kind}_entry",
    )
    def derive_entry(
        card_id: str,
        entry_id: str,
        payload: AssetDeriveRequest,
        request: Request,
        user: CurrentUser,
        session: DbSession,
        idempotency_key: IdempotencyKey,
        _: Write,
    ) -> AssetGenerateResponse:
        target_token = (
            payload.target_variant_id
            or f"new:{payload.new_variant.name if payload.new_variant else ''}"
        )
        key = _job_key(idempotency_key, "derive", entry_id, target_token, payload.output)
        if not payload.dry_run:
            # Before planning: a replayed derive created its look already,
            # and planning it again would refuse the now-taken name.
            replayed = _replay(session, user.id, key)
            if replayed is not None:
                return _replayed_response(session, user.id, payload.quality_tier, replayed)
        draft = (
            derive.NewVariantDraft(
                name=payload.new_variant.name,
                description=payload.new_variant.description,
                presets=payload.new_variant.presets.model_dump(exclude_none=True)
                if payload.new_variant.presets
                else {},
                attributes=payload.new_variant.attributes.model_dump(exclude_none=True)
                if payload.new_variant.attributes
                else {},
                scene_id=payload.new_variant.scene_id,
                scene_variant_id=payload.new_variant.scene_variant_id,
            )
            if payload.new_variant
            else None
        )
        plan = derive.plan_derive(
            session,
            user_id=user.id,
            kind=kind,
            card_id=card_id,
            entry_id=entry_id,
            output=payload.output,
            target_variant_id=payload.target_variant_id,
            new_variant=draft,
            prompt_extra=payload.prompt_extra,
            expressions=[str(e) for e in payload.expressions] if payload.expressions else None,
            aspect_ratio=payload.aspect_ratio,
        )
        credits, available, remaining, within = _quote(session, user.id, payload.quality_tier)
        response = AssetGenerateResponse(
            credits=credits,
            available_credits=available,
            period_remaining=remaining,
            within_spend_limit=within,
            sufficient=available >= credits and within,
            relations=[AssetRelation(r) for r in plan.relations],
        )
        if payload.dry_run:
            return response
        _check_funds(credits, available, remaining, within)
        skill = plan.skill
        target = plan.target
        if target is None:
            assert draft is not None
            target = av.create_variant(
                session,
                skill,
                name=draft.name,
                description=draft.description,
                presets=draft.presets,
                attributes=draft.attributes,
            )
            if draft.scene_id:
                av.set_scene_link(
                    session,
                    skill,
                    target,
                    scene_id=draft.scene_id,
                    scene_variant_id=draft.scene_variant_id,
                )
            # A new look is published content (CL invariant 3).
            skill_library_service.withdraw_after_edit(session, skill)
            session.flush()
        edge = None
        if target.id != plan.source.variant_id and plan.relations:
            edge = graph_service.add_auto_edge(
                session,
                skill,
                level=AssetGraphLevel.VARIANT,
                source_id=plan.source.variant_id,
                target_id=target.id,
                relations=plan.relations,
            )
        params = {**plan.params, "target_variant_id": target.id}
        if payload.output == "identity_portrait":
            params.pop("target_variant_id")
        job = _submit(
            session,
            request=request,
            user=user,
            quality_tier=payload.quality_tier,
            params=params,
            key=key,
        )
        return response.model_copy(
            update={
                "job_id": job.id,
                "variant_id": target.id,
                "edge_id": edge.id if edge else None,
            }
        )

    @router.post(
        f"/{prefix}/{{card_id}}/entries/{{entry_id}}:orbit",
        response_model=AssetGenerateResponse,
        operation_id=f"orbit_{kind}_entry",
    )
    def orbit_entry(
        card_id: str,
        entry_id: str,
        payload: AssetOrbitRequest,
        request: Request,
        user: CurrentUser,
        session: DbSession,
        idempotency_key: IdempotencyKey,
        _: Write,
    ) -> AssetGenerateResponse:
        poses = [camera_vocab.CameraPose(p.azimuth, p.elevation, p.distance) for p in payload.poses]
        token = ",".join("-".join(map(str, pose.bucket())) for pose in poses)
        key = _job_key(idempotency_key, "orbit", entry_id, token)
        if not payload.dry_run:
            replayed = _replay(session, user.id, key)
            if replayed is not None:
                return _replayed_response(session, user.id, payload.quality_tier, replayed)
        plan = derive.plan_orbit(
            session,
            user_id=user.id,
            kind=kind,
            card_id=card_id,
            entry_id=entry_id,
            poses=poses,
            aspect_ratio=payload.aspect_ratio,
        )
        planned = plan.params["camera_poses"]
        credits, available, remaining, within = _quote(
            session, user.id, payload.quality_tier, len(planned), Operation.IMAGE_TO_IMAGE
        )
        response = AssetGenerateResponse(
            credits=credits,
            available_credits=available,
            period_remaining=remaining,
            within_spend_limit=within,
            sufficient=available >= credits and within,
            variant_id=plan.source.variant_id,
            poses=[CameraPose.model_validate(pose) for pose in planned],
        )
        if payload.dry_run:
            return response
        _check_funds(credits, available, remaining, within)
        job = _submit(
            session,
            request=request,
            user=user,
            quality_tier=payload.quality_tier,
            params=plan.params,
            key=key,
            operation=Operation.IMAGE_TO_IMAGE,
        )
        return response.model_copy(update={"job_id": job.id})


_register("characters")
_register("scenes")
