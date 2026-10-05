"""`POST /v1/characters/{id}/looks/{look_id}:fill` — 补齐缺失 (P2-4,
`app.domain.characters.fill`).

`dry_run` (the default) reports each slot of the look's standard set and the
jobs that would fill the missing ones, with the exact total (`quote_for` per
job, balance and monthly cap like `quote:batch`). A submit refuses up front
when that total does not fit, then submits only the *next wave* — one job —
through the ordinary submit (quote, reserve, commit, enqueue). The client
calls again once it finishes: the plan is recomputed from the card, so the
call is naturally idempotent and resumable. The job's idempotency key is
derived from the request's and the slots it fills. Only a submit counts
against `generation_submit` (one hit per job); a dry run is a quote and
counts as an ordinary write.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api import rate_limit
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, client_identity, rate_limited
from app.api.schemas.asset_variants import (
    LookFillLineView,
    LookFillRequest,
    LookFillResponse,
)
from app.api.schemas.jobs import GenerationParams
from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters import fill
from app.domain.characters import service as characters_service
from app.domain.credits import service as credits_service
from app.domain.errors import InsufficientCredits, NotFound, SpendLimitExceeded
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import service as jobs_service
from app.models.base import new_id

router = APIRouter(tags=["asset-variants"])


@router.post(
    "/characters/{card_id}/looks/{look_id}:fill",
    response_model=LookFillResponse,
    operation_id="fill_character_look",
)
def fill_character_look(
    card_id: str,
    look_id: str,
    payload: LookFillRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> LookFillResponse:
    character = characters_service.get_character(session, user_id=user.id, character_id=card_id)
    look = asset_variants_service.find_variant(character.skill, look_id)
    if look is None:
        raise NotFound("造型不存在。")
    gaps = fill.gaps(character, look)
    lines = fill.plan(
        character,
        look,
        slots=list(payload.slots) if payload.slots else None,
        expressions=[str(e) for e in payload.expressions] if payload.expressions else None,
        aspect_ratio=payload.aspect_ratio,
    )
    priced = [
        (
            line,
            jobs_service.quote_for(
                session,
                operation=line.operation,
                quality_tier=payload.quality_tier,
                output_count=line.output_count,
            ).credits,
        )
        for line in lines
    ]
    total = sum(credits for _, credits in priced)
    account = credits_service.get_or_create_account(session, user.id)
    available = account.available_balance
    remaining = credits_service.remaining_monthly_spend(account)
    within = remaining is None or remaining >= total

    submitted_job_id: str | None = None
    submitted_slots: list[str] = []
    if not payload.dry_run and lines:
        if available < total:
            raise InsufficientCredits(
                f"需要 {total} 积分，当前可用 {available}。", required=total, available=available
            )
        if not within:
            raise SpendLimitExceeded(
                f"需要 {total} 积分，本月消费上限还剩 {remaining}。",
                required=total,
                remaining=remaining,
            )
        rate_limit.enforce("generation_submit", client_identity(request, user))
        line = lines[0]
        params = GenerationParams.model_validate(line.params).model_dump()
        token = hashlib.sha1(f"{look.id}:{','.join(line.slots)}".encode()).hexdigest()[:12]
        result = jobs_service.submit(
            session,
            user_id=user.id,
            operation=line.operation,
            quality_tier=payload.quality_tier,
            params=params,
            idempotency_key=f"{(idempotency_key or new_id('idk'))[:100]}:{token}",
        )
        session.commit()
        if not result.replayed:
            job_dispatch.enqueue_or_fail(session, result.job)
        submitted_job_id = result.job.id
        submitted_slots = list(line.slots)

    session.commit()
    return LookFillResponse(
        gaps=gaps,
        lines=[
            LookFillLineView(
                wave=line.wave,
                slots=list(line.slots),
                output_count=line.output_count,
                credits=credits,
            )
            for line, credits in priced
        ],
        total_credits=total,
        available_credits=available,
        period_remaining=remaining,
        within_spend_limit=within,
        sufficient=available >= total and within,
        submitted_job_id=submitted_job_id,
        submitted_slots=submitted_slots,
    )
