"""User and permission operations."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AdminUserView,
    DataRequestDecisionRequest,
    DataRequestView,
    RoleGrantRequest,
    SuspendRequest,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    Admin,
    AdminDangerous,
    AdminRead,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.compliance import service as compliance
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.models import CreditAccount, DataRequest, Profile, User, Work
from app.models.base import utcnow
from app.models.enums import DataRequestStatus, DataRequestType, UserRole, UserStatus

router = APIRouter(tags=["admin:users"])

ASSIGNABLE_ROLES = frozenset({r.value for r in UserRole})


@router.get("/users", response_model=Page[AdminUserView])
def list_users(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    q: str | None = Query(default=None, max_length=200),
    status: UserStatus | None = None,
    role: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AdminUserView]:
    stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.outerjoin(Profile, Profile.user_id == User.id).where(
            or_(
                func.lower(User.email).like(pattern),
                func.lower(Profile.handle).like(pattern),
                func.lower(Profile.display_name).like(pattern),
            )
        )
    if status:
        stmt = stmt.where(User.status == status)
    if role:
        stmt = stmt.where(User.roles.contains([role]))
    if cursor:
        stmt = stmt.where(User.id < cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[_view(session, u) for u in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/users/{user_id}", response_model=AdminUserView)
def get_user(user_id: str, session: DbSession, user: Viewer, _: AdminRead) -> AdminUserView:
    return _view(session, _load(session, user_id))


@router.post("/users/{user_id}/suspend", response_model=AdminUserView)
def suspend(
    user_id: str,
    payload: SuspendRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> AdminUserView:
    require_confirmation(payload.confirm)
    target = _load(session, user_id)
    if target.id == user.id:
        raise Conflict("不能封禁自己的账号。")

    before = {"status": target.status}
    target.status = UserStatus.SUSPENDED
    target.suspended_reason = payload.reason
    audit.record(
        session,
        actor=user,
        action="user.suspend",
        target_type="user",
        target_id=target.id,
        before=before,
        after={"status": target.status},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(session, target)


@router.post("/users/{user_id}/unsuspend", response_model=AdminUserView)
def unsuspend(
    user_id: str,
    payload: SuspendRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> AdminUserView:
    require_confirmation(payload.confirm)
    target = _load(session, user_id)
    before = {"status": target.status}
    target.status = UserStatus.ACTIVE
    target.suspended_reason = None
    audit.record(
        session,
        actor=user,
        action="user.unsuspend",
        target_type="user",
        target_id=target.id,
        before=before,
        after={"status": target.status},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(session, target)


@router.post("/users/{user_id}/roles", response_model=AdminUserView)
def grant_roles(
    user_id: str,
    payload: RoleGrantRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> AdminUserView:
    """Replaces the role set.

    Only an admin can reach this, and an admin cannot strip their own admin
    role — that is the classic way to lock everyone out of the console.
    """
    require_confirmation(payload.confirm)
    unknown = set(payload.roles) - ASSIGNABLE_ROLES
    if unknown:
        raise ValidationFailed(f"未知角色：{', '.join(sorted(unknown))}。")

    target = _load(session, user_id)
    if target.id == user.id and UserRole.ADMIN.value not in payload.roles:
        raise Conflict("不能移除自己的 admin 角色。")

    before = {"roles": list(target.roles)}
    target.roles = sorted(set(payload.roles))
    audit.record(
        session,
        actor=user,
        action="user.grant_role",
        target_type="user",
        target_id=target.id,
        before=before,
        after={"roles": target.roles},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(session, target)


@router.get("/data-requests", response_model=Page[DataRequestView])
def list_data_requests(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: DataRequestStatus | None = None,
) -> Page[DataRequestView]:
    stmt = select(DataRequest).order_by(DataRequest.created_at)
    if status:
        stmt = stmt.where(DataRequest.status == status)
    return Page(items=[DataRequestView.model_validate(r) for r in session.scalars(stmt)])


@router.post("/data-requests/{request_id}/decide", response_model=DataRequestView)
def decide_data_request(
    request_id: str,
    payload: DataRequestDecisionRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> DataRequestView:
    """Approves or rejects an export or deletion request.

    Approving a deletion anonymises the account but keeps lineage tombstones, so
    descendants can still resolve their provenance.
    """
    require_confirmation(payload.confirm)
    record = session.get(DataRequest, request_id)
    if record is None:
        raise NotFound("请求不存在。")
    if record.status != DataRequestStatus.PENDING:
        raise Conflict("该请求已处理。")

    before = {"status": record.status}
    if not payload.approve:
        record.status = DataRequestStatus.REJECTED
    elif record.type == DataRequestType.EXPORT:
        record.result_object_key = compliance.export_user_data(session, record.user_id)
        record.status = DataRequestStatus.COMPLETED
    else:
        compliance.anonymise_user(session, record.user_id, actor_user_id=user.id)
        record.status = DataRequestStatus.COMPLETED

    record.handled_by_user_id = user.id
    record.handled_at = utcnow()
    audit.record(
        session,
        actor=user,
        action=(
            "data_request.approve_deletion"
            if payload.approve and record.type == DataRequestType.DELETE
            else "data_request.decide"
        ),
        target_type="data_request",
        target_id=record.id,
        before=before,
        after={"status": record.status},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return DataRequestView.model_validate(record)


def _load(session, user_id: str) -> User:  # type: ignore[no-untyped-def]
    target = session.get(User, user_id)
    if target is None:
        raise NotFound("用户不存在。")
    return target


def _view(session, target: User) -> AdminUserView:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(Profile).where(Profile.user_id == target.id))
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == target.id))
    work_count = int(
        session.scalar(
            select(func.count()).select_from(Work).where(Work.owner_user_id == target.id)
        )
        or 0
    )
    return AdminUserView(
        id=target.id,
        email=target.email,
        handle=profile.handle if profile else None,
        display_name=profile.display_name if profile else None,
        status=UserStatus(target.status),
        roles=list(target.roles),
        region=target.region,
        available_credits=account.available_balance if account else 0,
        reserved_credits=account.reserved_balance if account else 0,
        work_count=work_count,
        created_at=target.created_at,
        last_login_at=target.last_login_at,
    )
