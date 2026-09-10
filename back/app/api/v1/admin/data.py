"""Data operations: storage usage, lifecycle, backup, restore and seeding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    BackupRecordView,
    BackupTriggerRequest,
    SeedRequest,
    StorageUsageResponse,
)
from app.api.schemas.common import OkResponse, Page
from app.api.v1.admin.deps import Admin, AdminDangerous, AdminRead, Viewer, require_confirmation
from app.config import get_settings
from app.domain.audit import service as audit
from app.domain.errors import Conflict
from app.domain.ops import backups as backups_service
from app.models import BackupRecord
from app.storage import s3

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin:data"])

# Staged uploads that were never completed are garbage after a day.
DEFAULT_LIFECYCLE_RULES = [
    {
        "ID": "expire-staging",
        "Status": "Enabled",
        "Filter": {"Prefix": "staging/"},
        "Expiration": {"Days": 1},
    },
    {
        "ID": "expire-exports",
        "Status": "Enabled",
        "Filter": {"Prefix": "exports/"},
        "Expiration": {"Days": 30},
    },
    # Both the admin-triggered and the daily scheduled backup
    # (`app.workers.tasks.run_scheduled_backup`) write here — without this,
    # a `pg_dump` archive every day forever is the exact unbounded-growth
    # pattern the rest of this bucket's rules exist to prevent. 60 days
    # comfortably outlives any plausible "restore last week's data" request.
    {
        "ID": "expire-backups",
        "Status": "Enabled",
        "Filter": {"Prefix": "backups/db/"},
        "Expiration": {"Days": 60},
    },
]


@router.get("/storage/usage", response_model=StorageUsageResponse)
def storage_usage(session: DbSession, user: Viewer, _: AdminRead) -> StorageUsageResponse:
    usage = s3.bucket_usage()
    return StorageUsageResponse(
        bucket=s3.active_bucket_name(),
        object_count=int(usage["object_count"]),
        total_bytes=int(usage["total_bytes"]),
        by_prefix=dict(usage.get("by_prefix", {})),
        lifecycle_rules=s3.lifecycle_rules(),
    )


@router.post("/storage/lifecycle", response_model=StorageUsageResponse)
def apply_lifecycle(
    request: Request, session: DbSession, user: Admin, _: AdminRead
) -> StorageUsageResponse:
    """Applies the standard retention rules to the bucket."""
    s3.put_lifecycle_rules(DEFAULT_LIFECYCLE_RULES)
    audit.record(
        session,
        actor=user,
        action="storage.lifecycle",
        target_type="bucket",
        target_id=s3.active_bucket_name(),
        after={"rules": [r["ID"] for r in DEFAULT_LIFECYCLE_RULES]},
        request=request,
    )
    session.commit()
    return storage_usage(session, user, None)


@router.get("/backups", response_model=Page[BackupRecordView])
def list_backups(session: DbSession, user: Viewer, _: AdminRead) -> Page[BackupRecordView]:
    rows = session.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(50))
    return Page(items=[BackupRecordView.model_validate(r) for r in rows])


@router.post("/backups", response_model=BackupRecordView, status_code=201)
def trigger_backup(
    payload: BackupTriggerRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> BackupRecordView:
    """Runs `pg_dump` and stores the archive in object storage.

    Synchronous on purpose: an operator triggering a backup before a risky
    change needs to know whether it actually succeeded.
    """
    require_confirmation(payload.confirm)
    record = BackupRecord(kind=payload.kind, status="running", triggered_by_user_id=user.id)
    session.add(record)
    session.flush()

    try:
        object_key, size = backups_service.run_database_backup()
        record.status = "succeeded"
        record.object_key = object_key
        record.size_bytes = size
    except Exception as exc:
        logger.exception("backup failed")
        record.status = "failed"
        record.message = f"{type(exc).__name__}: {exc}"[:500]

    audit.record(
        session,
        actor=user,
        action="data.backup",
        target_type="backup",
        target_id=record.id,
        after={"status": record.status, "object_key": record.object_key},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return BackupRecordView.model_validate(record)


@router.post("/seed", response_model=OkResponse)
def seed(
    payload: SeedRequest,
    request: Request,
    session: DbSession,
    user: Admin,
    _: AdminDangerous,
) -> OkResponse:
    """Loads demo data. Refused outright in production."""
    require_confirmation(payload.confirm)
    settings = get_settings()
    if settings.is_production:
        raise Conflict("生产环境禁止执行种子数据操作。")

    from app.scripts import seed as seed_script

    audit.record(
        session,
        actor=user,
        action="data.reset" if payload.reset else "data.seed",
        target_type="database",
        target_id=settings.app_env,
        after={"reset": payload.reset},
        reason=payload.reason,
        request=request,
    )
    session.commit()

    seed_script.run(reset=payload.reset)
    return OkResponse()
