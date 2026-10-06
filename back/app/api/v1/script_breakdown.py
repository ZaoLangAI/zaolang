"""剧本拆解建卡 (AC-9): `POST /v1/scripts/{id}:breakdown` proposes the
character / scene / prop cards a script needs; `…:breakdown-apply` creates
or links them and optionally queues each new card's first image.

Both sit behind `script_studio_enabled` and the `script_studio_write`
bucket (the proposal is an LLM call) and are open to the owner or an
active co-creator, like every other script route. The proposal writes
nothing.

Apply follows the scene matrix (`scene_matrix.py`): `dry_run` (the
default) validates and prices; a submit refuses up front when the first
images do not fit the balance or the monthly cap, counts one
`generation_submit` hit per image, then creates the cards, writes the
links and submits each image in its own savepoint — a refused image keeps
its card and the others' jobs. The whole outcome is remembered under the
request's `Idempotency-Key` in the same transaction, so a retry replays it
instead of creating twins.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api import idempotency, rate_limit
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, client_identity, rate_limited
from app.api.schemas.jobs import GenerationParams
from app.api.schemas.script import (
    ScriptBreakdownApplyRequest,
    ScriptBreakdownApplyResponse,
    ScriptBreakdownApplyResult,
    ScriptBreakdownItem,
    ScriptBreakdownMatch,
    ScriptBreakdownResponse,
    ScriptDocument,
)
from app.domain.credits import service as credits_service
from app.domain.errors import DomainError, InsufficientCredits, SpendLimitExceeded
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import service as jobs_service
from app.domain.script_writing import breakdown
from app.models import GenerationJob
from app.models.base import new_id
from app.models.enums import Operation

router = APIRouter(tags=["scripts"])

BREAKDOWN_APPLY_ENDPOINT = "POST /v1/scripts/{episode_id}:breakdown-apply"

StudioWrite = Annotated[None, Depends(rate_limited("script_studio_write"))]


def _item(item: breakdown.ProposedItem) -> ScriptBreakdownItem:
    return ScriptBreakdownItem.model_validate(
        {
            "kind": item.kind,
            "name": item.name,
            "description": item.description,
            "headings": item.headings,
            "age_stage": item.age_stage,
            "period": item.period,
            "lighting": item.lighting,
            "linked_card_id": item.linked_card_id,
            "matches": [ScriptBreakdownMatch(id=card.id, name=card.name) for card in item.matches],
        }
    )


@router.post(
    "/scripts/{episode_id}:breakdown",
    response_model=ScriptBreakdownResponse,
    operation_id="script_breakdown",
)
def script_breakdown(
    episode_id: str, user: CurrentUser, session: DbSession, _: StudioWrite
) -> ScriptBreakdownResponse:
    proposal = breakdown.propose(session, user_id=user.id, episode_id=episode_id)
    # The agent run is the only row written.
    session.commit()
    return ScriptBreakdownResponse(
        characters=[_item(item) for item in proposal.characters],
        scenes=[_item(item) for item in proposal.scenes],
        props=[_item(item) for item in proposal.props],
        degraded=proposal.degraded,
    )


@router.post(
    "/scripts/{episode_id}:breakdown-apply",
    response_model=ScriptBreakdownApplyResponse,
    operation_id="script_breakdown_apply",
)
def script_breakdown_apply(
    episode_id: str,
    payload: ScriptBreakdownApplyRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: StudioWrite,
) -> ScriptBreakdownApplyResponse:
    # A dry run is a quote: never remembered, so the same key still works
    # for the submit that follows it.
    remembered = bool(idempotency_key) and not payload.dry_run
    request_hash = idempotency.hash_request(
        {"episode_id": episode_id, **payload.model_dump(mode="json")}
    )
    if remembered:
        assert idempotency_key is not None
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=BREAKDOWN_APPLY_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return ScriptBreakdownApplyResponse.model_validate(replay.response_snapshot)

    plan = breakdown.plan_apply(
        session,
        user_id=user.id,
        episode_id=episode_id,
        items=[
            breakdown.ApplyItem(**item.model_dump(mode="json", exclude_none=False))
            for item in payload.items
        ],
        generate=payload.generate.enabled,
        quality_tier=payload.generate.quality_tier.value,
    )
    total = plan.total_credits
    account = credits_service.get_or_create_account(session, user.id)
    remaining = credits_service.remaining_monthly_spend(account)
    within = remaining is None or remaining >= total
    available = account.available_balance

    submitted = 0
    queued: list[GenerationJob] = []
    episode = plan.episode
    if not payload.dry_run:
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
        identity = client_identity(request, user)
        for _item_needing_image in plan.first_image_items():
            rate_limit.enforce("generation_submit", identity)

        episode = breakdown.write_cards(session, user_id=user.id, plan=plan)
        base_key = idempotency_key or new_id("idk")
        for item in plan.first_image_items():
            digest = hashlib.sha1(f"{item.kind}:{item.name}".encode()).hexdigest()[:12]
            try:
                with session.begin_nested():
                    params = GenerationParams.model_validate(
                        breakdown.first_image_params(session, user_id=user.id, item=item)
                    ).model_dump()
                    result = jobs_service.submit(
                        session,
                        user_id=user.id,
                        operation=Operation.TEXT_TO_IMAGE,
                        quality_tier=plan.quality_tier,
                        params=params,
                        # The key column holds 120 chars: a short digest per card.
                        idempotency_key=f"{base_key[:100]}:{digest}",
                    )
            except DomainError as exc:
                # One refused image (a provider gate, a cap reached by a
                # parallel submit) keeps its card and the other images.
                item.error = exc.message
                continue
            item.job_id = result.job.id
            submitted += 1
            if not result.replayed:
                queued.append(result.job)

    response = ScriptBreakdownApplyResponse(
        items=[
            ScriptBreakdownApplyResult(
                kind=item.kind,
                name=item.name,
                action=item.action,
                card_id=item.card_id,
                created=item.created,
                job_id=item.job_id,
                credits=item.credits,
                error=item.error,
            )
            for item in plan.items
        ],
        script=ScriptDocument.model_validate(episode.script_json or {}),
        total_credits=total,
        # As of the plan, before this request reserved anything.
        available_credits=available,
        period_remaining=remaining,
        within_spend_limit=within,
        sufficient=available >= total and within,
        submitted=submitted,
        dry_run=payload.dry_run,
    )
    if remembered:
        assert idempotency_key is not None
        # Same transaction as the cards and the reservations: a committed
        # apply always has its replay, a rolled-back one never does.
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=BREAKDOWN_APPLY_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=200,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    # After the commit: a worker that picks a job up before its row is
    # visible would find nothing.
    for job in queued:
        job_dispatch.enqueue_or_fail(session, job)
    return response
