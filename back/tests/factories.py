"""Object builders for tests.

Kept deliberately thin: each helper creates the minimum consistent state, so a
test that cares about one invariant does not accidentally depend on unrelated
defaults.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import GenerationJob, User, Work, WorkVersion
from app.models.base import new_id, utcnow
from app.models.enums import JobStatus, Operation, QualityTier, Visibility


def make_work(
    session: Session,
    owner: User,
    *,
    title: str = "深海霓虹",
    visibility: str = Visibility.PUBLIC_REMIXABLE,
    lifecycle_status: str = "active",
) -> tuple[Work, WorkVersion]:
    work = Work(
        owner_user_id=owner.id,
        visibility=visibility,
        lifecycle_status=lifecycle_status,
        published_at=utcnow(),
    )
    session.add(work)
    session.flush()

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        description="测试作品",
        reusable_params_json={"prompt": title, "seed": 42},
        immutable_created_at=utcnow(),
    )
    session.add(version)
    session.flush()

    work.current_version_id = version.id
    session.flush()
    return work, version


def make_job(
    session: Session,
    user: User,
    *,
    status: str = JobStatus.CREATED,
    quoted: int = 12,
    reserved: int = 12,
    operation: str = Operation.TEXT_TO_IMAGE,
    quality_tier: str = QualityTier.STANDARD,
) -> GenerationJob:
    job = GenerationJob(
        user_id=user.id,
        operation=operation,
        request_json={"prompt": "测试"},
        quality_tier=quality_tier,
        status=status,
        quoted_credits=quoted,
        reserved_credits=reserved,
        idempotency_key=new_id("idk"),
    )
    session.add(job)
    session.flush()
    return job
