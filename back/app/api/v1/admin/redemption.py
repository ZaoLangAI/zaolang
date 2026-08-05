"""Back-office issuance of invite/promo codes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession
from app.api.schemas.admin import (
    DangerousAction,
    RedemptionCodeCreateRequest,
    RedemptionCodeView,
    RedemptionRecordView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    AdminDangerous,
    AdminRead,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.credits import redemption
from app.domain.errors import NotFound
from app.models import RedemptionCode
from app.models.enums import RedemptionCodeKind

router = APIRouter(tags=["admin:credits"])


@router.get("/redemption-codes", response_model=Page[RedemptionCodeView])
def list_codes(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    kind: RedemptionCodeKind | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[RedemptionCodeView]:
    codes = redemption.list_codes(session, kind=kind, limit=limit)
    return Page(items=[_view(c) for c in codes])


@router.post("/redemption-codes", response_model=RedemptionCodeView)
def create_code(
    payload: RedemptionCodeCreateRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    __: AdminDangerous,
) -> RedemptionCodeView:
    require_confirmation(payload.confirm)
    entry = redemption.create_code(
        session,
        kind=payload.kind,
        credits=payload.credits,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
        note=payload.note,
        actor_user_id=user.id,
        code=payload.code,
    )
    audit.record(
        session,
        actor=user,
        action="redemption_code.create",
        target_type="redemption_code",
        target_id=entry.id,
        after={"code": entry.code, "credits": entry.credits, "max_uses": entry.max_uses},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(entry)


@router.post("/redemption-codes/{code_id}/deactivate", response_model=RedemptionCodeView)
def deactivate_code(
    code_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> RedemptionCodeView:
    """No way back once flipped — there is no `activate` endpoint — so this
    carries the same reason + confirm gate as minting a code does."""
    require_confirmation(payload.confirm)
    entry = session.get(RedemptionCode, code_id)
    if entry is None:
        raise NotFound("兑换码不存在。")

    before = {"is_active": entry.is_active}
    redemption.deactivate_code(session, code=entry)
    audit.record(
        session,
        actor=user,
        action="redemption_code.deactivate",
        target_type="redemption_code",
        target_id=entry.id,
        before=before,
        after={"is_active": entry.is_active},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(entry)


@router.get("/redemption-codes/{code_id}/records", response_model=Page[RedemptionRecordView])
def list_records(
    code_id: str, session: DbSession, user: Viewer, _: AdminRead
) -> Page[RedemptionRecordView]:
    if session.get(RedemptionCode, code_id) is None:
        raise NotFound("兑换码不存在。")
    records = redemption.list_records(session, code_id=code_id)
    return Page(
        items=[
            RedemptionRecordView(
                id=r.id, user_id=r.user_id, credits=r.credits, created_at=r.created_at
            )
            for r in records
        ]
    )


def _view(entry: RedemptionCode) -> RedemptionCodeView:
    return RedemptionCodeView(
        id=entry.id,
        code=entry.code,
        kind=RedemptionCodeKind(entry.kind),
        credits=entry.credits,
        max_uses=entry.max_uses,
        used_count=entry.used_count,
        expires_at=entry.expires_at,
        is_active=entry.is_active,
        note=entry.note,
        created_by_user_id=entry.created_by_user_id,
        created_at=entry.created_at,
    )
