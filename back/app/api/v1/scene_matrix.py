"""`POST /v1/scenes/{id}/variants:matrix` — a scene card's lighting ×
weather × state × period matrix, planned, priced and submitted as one image
job per new cell (P2-5, `app.domain.scenes.matrix`).

`dry_run` (the default) returns every cell with what the card already holds
and the exact total a submit would reserve — the same `quote_for` a submit
uses, summed, plus the balance and monthly-cap checks `quote:batch` does. A
submit refuses up front when the total does not fit, so a short balance never
leaves half a matrix queued; each cell then goes through the ordinary submit
(quote, reserve, commit, enqueue) with its own idempotency key derived from
the request's, so a retried request replays instead of double-charging. It
counts one `generation_submit` hit per job.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api import rate_limit
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, client_identity, rate_limited
from app.api.schemas.asset_variants import (
    SceneMatrixCellView,
    SceneMatrixRequest,
    SceneMatrixResponse,
)
from app.api.schemas.jobs import GenerationParams
from app.domain.credits import service as credits_service
from app.domain.errors import DomainError, InsufficientCredits, SpendLimitExceeded
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import service as jobs_service
from app.domain.scenes import matrix
from app.domain.scenes import service as scenes_service
from app.models.base import new_id
from app.models.enums import Operation

router = APIRouter(tags=["asset-variants"])


@router.post(
    "/scenes/{card_id}/variants:matrix",
    response_model=SceneMatrixResponse,
    operation_id="scene_variant_matrix",
)
def scene_variant_matrix(
    card_id: str,
    payload: SceneMatrixRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("generation_submit"))],
) -> SceneMatrixResponse:
    skill = scenes_service.get_scene(session, user_id=user.id, scene_id=card_id).skill
    cells = matrix.plan(skill, payload.axes.model_dump())
    new_cells = [cell for cell in cells if cell.status == "new"]
    unit = jobs_service.quote_for(
        session, operation=Operation.TEXT_TO_IMAGE, quality_tier=payload.quality_tier
    ).credits
    total = unit * len(new_cells)
    account = credits_service.get_or_create_account(session, user.id)
    remaining = credits_service.remaining_monthly_spend(account)
    within = remaining is None or remaining >= total
    available = account.available_balance
    views = {
        cell.key: SceneMatrixCellView(
            presets=cell.presets, label=cell.label, status=cell.status, variant_id=cell.variant_id
        )
        for cell in cells
    }

    submitted = 0
    if not payload.dry_run and new_cells:
        if account.available_balance < total:
            raise InsufficientCredits(
                f"需要 {total} 积分，当前可用 {account.available_balance}。",
                required=total,
                available=account.available_balance,
            )
        if not within:
            raise SpendLimitExceeded(
                f"需要 {total} 积分，本月消费上限还剩 {remaining}。",
                required=total,
                remaining=remaining,
            )
        # The dependency counted this request once; every further job counts too.
        identity = client_identity(request, user)
        for _cell in new_cells[1:]:
            rate_limit.enforce("generation_submit", identity)

        prompt = (payload.prompt or "").strip() or matrix.default_prompt(skill)
        base_key = idempotency_key or new_id("idk")
        for cell in new_cells:
            view = views[cell.key]
            try:
                params = GenerationParams.model_validate(
                    matrix.cell_params(
                        skill, cell, prompt=prompt, aspect_ratio=payload.aspect_ratio
                    )
                ).model_dump()
                result = jobs_service.submit(
                    session,
                    user_id=user.id,
                    operation=Operation.TEXT_TO_IMAGE,
                    quality_tier=payload.quality_tier,
                    params=params,
                    # The key column holds 120 chars: a short digest of the cell.
                    idempotency_key=(
                        f"{base_key[:100]}:{hashlib.sha1(cell.key.encode()).hexdigest()[:12]}"
                    ),
                )
                session.commit()
            except DomainError as exc:
                # One cell failing (a cap reached by a parallel submit, a
                # provider gate) must not drop the cells already queued.
                session.rollback()
                view.error = exc.message
                continue
            if not result.replayed:
                job_dispatch.enqueue_or_fail(session, result.job)
            view.job_id = result.job.id
            submitted += 1

    session.commit()
    return SceneMatrixResponse(
        cells=list(views.values()),
        unit_credits=unit,
        total_credits=total,
        # As of the plan, before this request reserved anything.
        available_credits=available,
        period_remaining=remaining,
        within_spend_limit=within,
        sufficient=available >= total and within,
        submitted=submitted,
    )
