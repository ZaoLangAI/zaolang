"""The rows the Playwright suites walk, kept out of `make seed`.

`make seed` loads only login accounts and system defaults — demo business data
was taken out of it on purpose, so a fresh local environment starts empty. The
end-to-end suites still need something real to find: a public remix chain with
a withdrawn middle node, a paid work, a paid skill, a draft waiting to be
published and a failed job with its runtime log. This script plants exactly
those, for the e2e run and nothing else.

Two rules shape it:

* **Created once, found by a marker.** Every fixture job carries
  `idempotency_key="e2e-fixture:<slug>"`, and works are found through their
  version's job. A second run adds nothing, so repeated runs do not grow the
  feed.
* **Reset what the specs change.** A spec that likes a work or unlocks a paid
  one leaves that state behind, and the next run's "click 点赞" would then find
  the button already pressed. Each run clears the like, tops the buyer's
  balance back up, and — because a purchase is permanent (its ledger key is
  one per buyer and subject, so the same work can never be bought twice) —
  withdraws a paid work the buyer already owns and publishes a fresh one in
  its place rather than pretending the purchase never happened.

It writes rows directly rather than through the publish API, for the same
reason the old seed did: the chain needs a tombstoned middle node, which the
normal flow would never create, and publishing goes through a worker.

Run with `make e2e-fixtures` (writes `front/e2e/.fixtures.json` for the specs)
after `make seed`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.domain.credits import service as credits_service
from app.domain.lineage import service as lineage_service
from app.domain.search import service as search_service
from app.models import (
    AccessGrant,
    Asset,
    CreationSkill,
    Draft,
    GenerationJob,
    JobEvent,
    LicenseSnapshot,
    Like,
    Profile,
    SystemLog,
    User,
    Work,
    WorkVersion,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    AccessSubjectType,
    AssetRole,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    JobEventType,
    JobStatus,
    LicenseType,
    LifecycleStatus,
    MediaType,
    ModerationStatus,
    Operation,
    QualityTier,
    SystemLogLevel,
    SystemLogSource,
    Visibility,
)
from app.storage import s3

logger = logging.getLogger(__name__)

MARKER = "e2e-fixture"
CARD_LONG_EDGE = 1280

# Titles the specs look for. Kept in step with `front/e2e/flows/consumer.spec.ts`.
ROOT_TITLE = "潮汐之上"
FREE_REMIX_TITLE = "潮汐之上 · 夜行"
WITHDRAWN_TITLE = "Night Tide (withdrawn)"
DEEP_REMIX_TITLE = "Night Tide · Neon"
PAID_WORK_TITLE = "潮汐之上 · 付费样例"
PAID_WORK_CREDITS = 10
PAID_SKILL_TITLE = "黄金时刻镜头"
PAID_SKILL_CREDITS = 8
DRAFT_TITLE = "潮汐之上 · 未完成"
# What `workers/async_polling._give_up_on_dead_upstream` writes when a render
# never answers — the fixture mirrors it rather than inventing its own signal.
FAILED_JOB_LOG_EVENT = "async_task_poll_budget_exceeded"
FAILED_JOB_CODE = "PROVIDER_TIMEOUT"

# Enough for the paid-work unlock plus a few generations, without letting the
# account drift upwards run after run.
BUYER_BALANCE_FLOOR = 500


@dataclass(frozen=True)
class Manifest:
    """Ids the specs cannot find by title alone."""

    free_remix_work_id: str
    withdrawn_work_id: str
    paid_work_id: str
    paid_skill_id: str
    draft_id: str
    failed_job_id: str


def run(session: Session) -> Manifest:
    """Plants (or re-finds) every fixture, then resets per-run state."""
    if get_settings().is_production:
        raise RuntimeError("拒绝在生产环境写入 E2E 数据。")
    users = _seed_users(session)
    linhai, mizuki, ava = users["linhai"], users["mizuki"], users["ava"]

    root = _published(
        session,
        slug="chain-root",
        owner=linhai,
        title=ROOT_TITLE,
        description="海面在黎明前最安静的那三十秒。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        params={
            "prompt": "aerial shot of a calm ocean before dawn, long lens, film grain",
            "seed": 20260101,
            "style_tags": ["cinematic", "ocean"],
            "aspect_ratio": "21:9",
        },
        tier=QualityTier.CINEMATIC,
    )
    free_remix = _published(
        session,
        slug="chain-free-remix",
        owner=mizuki,
        title=FREE_REMIX_TITLE,
        description="把黎明换成夜色，把安静换成呼吸。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        params={
            "prompt": "aerial shot of a night ocean, moonlight, long lens, film grain",
            "seed": 20260214,
            "style_tags": ["cinematic", "night"],
            "aspect_ratio": "21:9",
        },
        tier=QualityTier.STANDARD,
        parent=root,
    )
    withdrawn = _published(
        session,
        slug="chain-withdrawn",
        owner=ava,
        title=WITHDRAWN_TITLE,
        description="A version its author later withdrew.",
        visibility=Visibility.PUBLIC_REMIXABLE,
        params={"prompt": "monochrome night tide, heavy grain", "seed": 7},
        tier=QualityTier.PREVIEW,
        parent=free_remix,
    )
    if withdrawn.lifecycle_status != LifecycleStatus.TOMBSTONE:
        # Withdrawn after publishing: it keeps its place in the lineage as a
        # tombstone but must leave every public list.
        _withdraw(withdrawn, reason="author_withdrew")
    _published(
        session,
        slug="chain-deep-remix",
        owner=ava,
        title=DEEP_REMIX_TITLE,
        description="Third-generation remix. The chain still resolves through a tombstone.",
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        params={"prompt": "neon night tide, reflections, slow motion", "seed": 991},
        tier=QualityTier.STANDARD,
        parent=withdrawn,
    )
    paid = _unowned_paid_work(session, owner=linhai, buyer=mizuki)
    skill = _paid_skill(session, owner=linhai)
    draft = _draft(session, owner=mizuki, source=free_remix)
    failed = _failed_job(session, owner=mizuki)

    _reset_spec_state(session, liker=linhai, liked=free_remix, buyer=mizuki)
    session.flush()
    return Manifest(
        free_remix_work_id=free_remix.id,
        withdrawn_work_id=withdrawn.id,
        paid_work_id=paid.id,
        paid_skill_id=skill.id,
        draft_id=draft.id,
        failed_job_id=failed.id,
    )


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


def _seed_users(session: Session) -> dict[str, User]:
    handles = ("linhai", "mizuki", "ava")
    rows = session.execute(
        select(Profile.handle, User)
        .join(User, User.id == Profile.user_id)
        .where(Profile.handle.in_(handles))
    ).all()
    users: dict[str, User] = {row[0]: row[1] for row in rows}
    missing = [handle for handle in handles if handle not in users]
    if missing:
        raise RuntimeError(f"缺少种子账号 {missing}，请先执行 make seed。")
    return users


# --------------------------------------------------------------------------
# Works
# --------------------------------------------------------------------------


def _key(slug: str) -> str:
    return f"{MARKER}:{slug}"


def _find_job(session: Session, slug: str) -> GenerationJob | None:
    return session.scalar(select(GenerationJob).where(GenerationJob.idempotency_key == _key(slug)))


def _published(
    session: Session,
    *,
    slug: str,
    owner: User,
    title: str,
    description: str,
    visibility: str,
    params: dict[str, Any],
    tier: str,
    parent: Work | None = None,
    access_credits: int = 0,
    asset_slug: str | None = None,
) -> Work:
    """A published work with its asset, finished job and lineage edge."""
    existing_job = _find_job(session, slug)
    if existing_job is not None:
        work = session.scalar(
            select(Work)
            .join(WorkVersion, WorkVersion.work_id == Work.id)
            .where(WorkVersion.generation_job_id == existing_job.id)
        )
        if work is not None:
            return work

    asset = _asset(
        session,
        owner=owner,
        slug=asset_slug or slug,
        label=title,
        aspect=params.get("aspect_ratio"),
    )
    job = _completed_job(session, slug=slug, owner=owner, params=params, tier=tier, asset=asset)

    work = Work(
        owner_user_id=owner.id,
        visibility=visibility,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
        view_count=120 + len(title) * 7,
        like_count=0,
        remix_count=0,
        access_credits=access_credits,
    )
    session.add(work)
    session.flush()

    snapshot_id: str | None = None
    parent_version: WorkVersion | None = None
    if parent is not None:
        parent_version = session.get(WorkVersion, parent.current_version_id or "")
        assert parent_version is not None
        snapshot = LicenseSnapshot(
            license_type=LicenseType.CC_BY_4_0,
            permissions_json={"remix": True, "commercial": False, "share_alike": False},
            attribution_text=f"基于 {parent_version.title} 创作",
            source_work_version_id=parent_version.id,
            captured_at=utcnow(),
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        description=description,
        cover_asset_id=asset.id,
        primary_output_asset_id=asset.id,
        ai_generated=True,
        generation_job_id=job.id,
        license_snapshot_id=snapshot_id,
        reusable_params_json=params if Visibility(visibility).allows_remix else {},
        immutable_created_at=utcnow(),
    )
    session.add(version)
    session.flush()
    work.current_version_id = version.id

    if parent is not None and parent_version is not None and snapshot_id:
        parent_owner = session.get(User, parent.owner_user_id)
        parent_profile = session.scalar(
            select(Profile).where(Profile.user_id == parent.owner_user_id)
        )
        assert parent_owner is not None
        lineage_service.create_edge(
            session,
            parent_version_id=parent_version.id,
            child_version_id=version.id,
            parent_author_snapshot={
                "user_id": parent_owner.id,
                "display_name": parent_profile.display_name if parent_profile else "",
                "handle": parent_profile.handle if parent_profile else "",
            },
            license_snapshot_id=snapshot_id,
            workflow_version_id=None,
            reused_asset_ids=[],
            created_by_user_id=owner.id,
        )
        parent.remix_count += 1

    search_service.index_version(session, work=work, version=version)
    session.flush()
    logger.info("e2e fixture: published %s (%s)", title, work.id)
    return work


def _asset(session: Session, *, owner: User, slug: str, label: str, aspect: Any = None) -> Asset:
    """A clearly-marked placeholder image, uploaded under a stable key.

    Stable so a re-run after a database reset overwrites the object rather than
    leaving one more behind in the bucket.
    """
    object_key = f"e2e-fixtures/{slug}.png"
    existing = session.scalar(select(Asset).where(Asset.object_key == object_key))
    if existing is not None:
        return existing

    width, height = _card_size(str(aspect or "16:9"))
    payload = _render_card(label, width, height)
    s3.put_object(object_key, payload, content_type="image/png")
    asset = Asset(
        owner_user_id=owner.id,
        object_key=object_key,
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=AssetRole.GENERATION_OUTPUT,
        width=width,
        height=height,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        is_prototype=True,
    )
    session.add(asset)
    session.flush()
    return asset


def _card_size(aspect: str) -> tuple[int, int]:
    try:
        w_part, h_part = (int(part) for part in aspect.split(":", 1))
    except ValueError:
        w_part, h_part = 16, 9
    if w_part <= 0 or h_part <= 0:
        w_part, h_part = 16, 9
    if w_part >= h_part:
        return CARD_LONG_EDGE, round(CARD_LONG_EDGE * h_part / w_part)
    return round(CARD_LONG_EDGE * w_part / h_part), CARD_LONG_EDGE


def _render_card(label: str, width: int, height: int) -> bytes:
    seed = int.from_bytes(hashlib.sha256(label.encode()).digest()[:8], "big")
    top = ((seed >> 16) % 40 + 8, (seed >> 8) % 30 + 12, seed % 70 + 40)
    bottom = ((seed >> 4) % 70 + 30, (seed >> 12) % 50 + 24, (seed >> 20) % 110 + 90)

    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / (height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * blend) for i in range(3)),
        )
    draw.rectangle([(0, height - 48), (width, height)], fill=(0, 0, 0))
    draw.text((24, height - 32), f"E2E FIXTURE · {label}", fill=(235, 235, 235))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _completed_job(
    session: Session,
    *,
    slug: str,
    owner: User,
    params: dict[str, Any],
    tier: str,
    asset: Asset,
) -> GenerationJob:
    """A finished, paid-for job with a full event trail."""
    existing = _find_job(session, slug)
    if existing is not None:
        return existing

    cost = {"preview": 4, "standard": 12, "cinematic": 40}.get(str(tier), 12)
    now = utcnow()
    job = GenerationJob(
        user_id=owner.id,
        operation=Operation.TEXT_TO_IMAGE,
        request_json=params,
        quality_tier=tier,
        status=JobStatus.SUCCEEDED,
        quoted_credits=cost,
        reserved_credits=cost,
        actual_credits=cost,
        idempotency_key=_key(slug),
        # No invented provider routing: real routing metadata only appears once
        # an endpoint is configured in Models.
        selected_route_summary_json={},
        routing_trace_json=[],
        output_asset_id=asset.id,
        estimated_seconds=25,
        started_at=now,
        finished_at=now,
    )
    session.add(job)
    session.flush()

    # Paid for like a real job, so the owner's ledger explains the spend.
    _ensure_balance(session, owner, cost)
    credits_service.reserve(session, owner.id, cost, job_id=job.id)
    credits_service.capture(session, owner.id, job_id=job.id, actual_amount=cost)

    steps = [
        (JobEventType.QUEUED, JobStatus.CREATED, 2, "任务已创建，正在排队。"),
        (JobEventType.SAFETY, JobStatus.RUNNING, 12, "安全检查通过。"),
        (JobEventType.GENERATING, JobStatus.RUNNING, 70, "正在生成画面。"),
        (JobEventType.SUCCEEDED, JobStatus.SUCCEEDED, 100, "生成完成。"),
    ]
    for sequence, (event_type, status, progress, message) in enumerate(steps, start=1):
        session.add(
            JobEvent(
                job_id=job.id,
                sequence=sequence,
                event_type=event_type,
                status=status,
                progress=progress,
                public_message=message,
                created_at=now,
            )
        )
    session.flush()
    return job


def _unowned_paid_work(session: Session, *, owner: User, buyer: User) -> Work:
    """The current paid work, guaranteed not yet bought by `buyer`.

    Each generation gets its own slug (`paid-work`, `paid-work-1`, ...). One the
    buyer already owns is withdrawn, the way its author would, and the next
    generation is published — so the unlock spec always meets a paywall and a
    purchase that did happen stays on the books.
    """
    generation = 0
    while True:
        slug = "paid-work" if generation == 0 else f"paid-work-{generation}"
        job = _find_job(session, slug)
        if job is None:
            break
        work = session.scalar(
            select(Work)
            .join(WorkVersion, WorkVersion.work_id == Work.id)
            .where(WorkVersion.generation_job_id == job.id)
        )
        if work is not None and work.lifecycle_status == LifecycleStatus.ACTIVE:
            owned = session.scalar(
                select(AccessGrant.id).where(
                    AccessGrant.buyer_user_id == buyer.id,
                    AccessGrant.subject_type == AccessSubjectType.WORK,
                    AccessGrant.subject_id == work.id,
                )
            )
            if owned is None:
                return work
            _withdraw(work, reason="e2e_fixture_superseded")
        generation += 1

    return _published(
        session,
        slug=slug,
        owner=owner,
        title=PAID_WORK_TITLE,
        description="用积分解锁后即可二创的样例作品。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        params={
            "prompt": "paid remix sample, aerial ocean, film grain",
            "seed": 20260814,
            "style_tags": ["cinematic"],
            "aspect_ratio": "21:9",
        },
        tier=QualityTier.STANDARD,
        access_credits=PAID_WORK_CREDITS,
        # One placeholder for every generation; they are the same picture.
        asset_slug="paid-work",
    )


def _withdraw(work: Work, *, reason: str) -> None:
    """Tombstoned the way an author withdraws a work: kept for lineage and
    for the receipts that reference it, gone from every public list."""
    work.lifecycle_status = LifecycleStatus.TOMBSTONE
    work.tombstoned_at = utcnow()
    work.tombstone_reason = reason
    work.visibility = Visibility.PRIVATE


# --------------------------------------------------------------------------
# Skill, draft, failed job
# --------------------------------------------------------------------------


def _paid_skill(session: Session, *, owner: User) -> CreationSkill:
    existing = session.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == owner.id, CreationSkill.title == PAID_SKILL_TITLE
        )
    )
    if existing is not None:
        return existing
    skill = CreationSkill(
        owner_user_id=owner.id,
        title=PAID_SKILL_TITLE,
        description="付费解锁后可套用的镜头技能样例。",
        category=CreationSkillCategory.LENS,
        params_json={"prompt_suffix": "golden hour, anamorphic flare"},
        visibility=CreationSkillVisibility.PUBLIC,
        status=CreationSkillStatus.PUBLISHED,
        access_credits=PAID_SKILL_CREDITS,
    )
    session.add(skill)
    session.flush()
    return skill


def _draft(session: Session, *, owner: User, source: Work) -> Draft:
    """A remix that finished generating and is waiting to be published."""
    existing = session.scalar(
        select(Draft).where(Draft.user_id == owner.id, Draft.title == DRAFT_TITLE)
    )
    if existing is not None:
        return existing

    params = {"prompt": "slow push in on wet asphalt, night ocean", "seed": 4242}
    asset = _asset(session, owner=owner, slug="draft-output", label=DRAFT_TITLE)
    job = _completed_job(
        session, slug="draft-output", owner=owner, params=params, tier="standard", asset=asset
    )
    draft = Draft(
        user_id=owner.id,
        source_work_version_id=source.current_version_id,
        title=DRAFT_TITLE,
        description="还在调节镜头推进的速度。",
        params_json=params,
        latest_job_id=job.id,
        applied_job_id=job.id,
        output_asset_id=asset.id,
    )
    session.add(draft)
    session.flush()
    return draft


def _failed_job(session: Session, *, owner: User) -> GenerationJob:
    """A job whose provider never answered, with the log that says so.

    Planted in the state the poller's give-up path leaves one in: failed with
    `PROVIDER_TIMEOUT`, reservation released, one `async_task_poll_budget_exceeded`
    row. A job left `running` would instead depend on whether a beat worker
    happens to be up during the run.
    """
    slug = "failed-job"
    existing = _find_job(session, slug)
    if existing is not None:
        return existing

    stale = utcnow() - dt.timedelta(hours=6)
    job = GenerationJob(
        user_id=owner.id,
        operation=Operation.IMAGE_TO_VIDEO,
        request_json={"prompt": "slow push in on wet asphalt", "seed": 4242},
        quality_tier=QualityTier.STANDARD,
        status=JobStatus.FAILED,
        quoted_credits=12,
        reserved_credits=12,
        idempotency_key=_key(slug),
        failure_code=FAILED_JOB_CODE,
        failure_message="外部渲染任务长时间未返回结果，预扣积分已退回。",
        estimated_seconds=40,
        started_at=stale,
        finished_at=stale + dt.timedelta(minutes=10),
        created_at=stale,
    )
    session.add(job)
    session.flush()
    _ensure_balance(session, owner, 12)
    credits_service.reserve(session, owner.id, 12, job_id=job.id)
    credits_service.release(session, owner.id, job_id=job.id, reason=FAILED_JOB_CODE.lower())

    for sequence, (event_type, status, progress, message) in enumerate(
        [
            (JobEventType.QUEUED, JobStatus.CREATED, 2, "任务已创建，正在排队。"),
            (JobEventType.GENERATING, JobStatus.RUNNING, 55, "正在生成画面。"),
            (JobEventType.FAILED, JobStatus.FAILED, 100, "生成超时，预扣积分已退回。"),
        ],
        start=1,
    ):
        session.add(
            JobEvent(
                job_id=job.id,
                sequence=sequence,
                event_type=event_type,
                status=status,
                progress=progress,
                public_message=message,
                created_at=stale,
            )
        )
    session.add(
        SystemLog(
            source=SystemLogSource.PIPELINE.value,
            event=FAILED_JOB_LOG_EVENT,
            level=SystemLogLevel.WARNING.value,
            message="外部渲染任务长时间未返回结果，已放弃轮询并释放预留积分",
            dedup_key=f"job:{job.id}",
            window_started_at=stale,
            occurrence_count=1,
            job_id=job.id,
            details_json={"async_task_id": "e2e-fixture-task", "poll_count": 37},
            created_at=stale,
        )
    )
    session.flush()
    return job


# --------------------------------------------------------------------------
# Per-run reset
# --------------------------------------------------------------------------


def _reset_spec_state(
    session: Session,
    *,
    liker: User,
    liked: Work,
    buyer: User,
) -> None:
    """Puts back what the specs change, so every run starts from the same place.

    Purchases are not in here: see `_unowned_paid_work`.
    """
    like = session.scalar(select(Like).where(Like.user_id == liker.id, Like.work_id == liked.id))
    if like is not None:
        session.delete(like)
        liked.like_count = max(0, liked.like_count - 1)
    _ensure_balance(session, buyer, BUYER_BALANCE_FLOOR)


def _ensure_balance(session: Session, user: User, floor: int) -> None:
    account = credits_service.get_or_create_account(session, user.id)
    shortfall = floor - account.available_balance
    if shortfall > 0:
        credits_service.grant(
            session,
            user.id,
            shortfall,
            idempotency_key=new_id("grant"),
            metadata={"source": MARKER},
        )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="载入 E2E 测试所需的固定数据")
    parser.add_argument("--manifest", type=Path, help="把 fixture id 写入该 JSON 文件")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    with session_scope() as session:
        manifest = run(session)

    body = json.dumps(asdict(manifest), ensure_ascii=False, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(body + "\n", encoding="utf-8")
        logger.info("e2e fixture manifest written to %s", args.manifest)
    sys.stdout.write(body + "\n")


if __name__ == "__main__":
    main()
