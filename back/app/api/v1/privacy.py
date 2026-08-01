"""Data subject rights from the user's side.

Requests are queued rather than executed: erasure anonymises an account and
tombstones its works, which is irreversible and therefore goes past a human in
`/v1/admin/data-requests` first.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.common import ApiModel, Page
from app.domain.compliance import service as compliance
from app.domain.errors import Conflict
from app.models import DataRequest
from app.models.enums import DataRequestStatus, DataRequestType

router = APIRouter(tags=["privacy"])


class DataRequestCreate(ApiModel):
    type: DataRequestType
    reason: str | None = Field(default=None, max_length=500)


class MyDataRequestView(ApiModel):
    id: str
    type: DataRequestType
    status: DataRequestStatus
    reason: str | None = None
    created_at: dt.datetime
    handled_at: dt.datetime | None = None
    download_url: str | None = None
    """Signed and short-lived; absent until an approved export has been built."""


@router.post("/me/data-requests", response_model=MyDataRequestView, status_code=201)
def create_data_request(
    payload: DataRequestCreate, user: CurrentUser, session: DbSession
) -> MyDataRequestView:
    pending = session.scalar(
        select(DataRequest).where(
            DataRequest.user_id == user.id,
            DataRequest.type == payload.type,
            DataRequest.status == DataRequestStatus.PENDING,
        )
    )
    if pending is not None:
        # Queuing a second identical request would only give the reviewer two
        # copies of the same decision to make.
        raise Conflict("同类请求已在处理中。")

    record = DataRequest(
        user_id=user.id,
        type=payload.type,
        status=DataRequestStatus.PENDING,
        note=payload.reason,
    )
    session.add(record)
    session.commit()
    return _view(record)


@router.get("/me/data-requests", response_model=Page[MyDataRequestView])
def list_my_data_requests(user: CurrentUser, session: DbSession) -> Page[MyDataRequestView]:
    records = session.scalars(
        select(DataRequest)
        .where(DataRequest.user_id == user.id)
        .order_by(DataRequest.created_at.desc())
        .limit(20)
    )
    return Page(items=[_view(record) for record in records])


def _view(record: DataRequest) -> MyDataRequestView:
    return MyDataRequestView(
        id=record.id,
        type=DataRequestType(record.type),
        status=DataRequestStatus(record.status),
        reason=record.note,
        created_at=record.created_at,
        handled_at=record.handled_at,
        download_url=(
            compliance.signed_export_url(record.result_object_key)
            if record.result_object_key
            else None
        ),
    )
