"""Draft creation and publication.

Publishing runs as one transaction with a fixed order. Either every step lands
or none does, because a work that exists without its lineage edge would be an
unattributed remix — exactly what the platform promises cannot happen.

    1. re-check the remix licence         5. create the lineage edge
    2. safety review the final content    6. index for discovery
    3. create work and version            7. pay ancestor royalties
    4. publish the media assets           8. notify the ancestors
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.credits.royalty import RoyaltyRule, distribute
from app.domain.errors import (
    Conflict,
    Forbidden,
    ModerationRejected,
    NotFound,
    ValidationFailed,
)
from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage
from app.domain.media import service as media_service
from app.domain.notifications import push as notifications
from app.domain.search import service as search_service
from app.models import (
    Asset,
    Draft,
    LineageEdge,
    Tag,
    Work,
    WorkTag,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    LifecycleStatus,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import RoyaltyConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishOutcome:
    work: Work
    version: WorkVersion
    lineage_edge: LineageEdge | None = None
    royalties: list[dict[str, Any]] = field(default_factory=list)


def create_draft(
    session: Session,
    *,
    user_id: str,
    source_work_id: str | None,
    title: str | None = None,
    params: dict[str, Any] | None = None,
) -> Draft:
    """Starts a draft, freezing the source licence at this moment."""
    source_version_id: str | None = None
    license_snapshot_id: str | None = None
    seeded_params = dict(params or {})

    if source_work_id:
        work = session.get(Work, source_work_id)
        if work is None:
            raise NotFound("来源作品不存在。")
        licensing.assert_remixable(work, user_id)

        version = session.get(WorkVersion, work.current_version_id or "")
        if version is None:
            raise NotFound("来源作品没有可用版本。")

        snapshot = licensing.capture_license_snapshot(session, source_version=version, work=work)
        source_version_id = version.id
        license_snapshot_id = snapshot.id
        # Carry over the author's reusable parameters unless the remixer
        # already supplied their own.
        for key, value in (version.reusable_params_json or {}).items():
            seeded_params.setdefault(key, value)

    draft = Draft(
        user_id=user_id,
        source_work_version_id=source_version_id,
        license_snapshot_id=license_snapshot_id,
        title=title,
        params_json=seeded_params,
    )
    session.add(draft)
    session.flush()
    return draft


def publish(
    session: Session,
    *,
    user_id: str,
    draft_id: str,
    title: str,
    description: str | None,
    visibility: str,
    tags: list[str],
    cover_asset_id: str | None,
    rights_confirmed: bool,
) -> PublishOutcome:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise NotFound("草稿不存在。")
    if draft.user_id != user_id:
        raise Forbidden("不能发布他人的草稿。")
    if draft.published_work_id is not None:
        raise Conflict("该草稿已经发布。")
    if draft.output_asset_id is None:
        raise ValidationFailed("草稿还没有生成结果，无法发布。")
    if not rights_confirmed:
        raise ValidationFailed(
            "请先确认你拥有所有新增素材的使用权。", fields={"rights_confirmed": "必须勾选"}
        )

    # 1. The source may have been locked down since the draft was created.
    source_version: WorkVersion | None = None
    if draft.source_work_version_id:
        source_version = session.get(WorkVersion, draft.source_work_version_id)
        if source_version is None:
            raise NotFound("来源版本不存在。")
        source_work = session.get(Work, source_version.work_id)
        if source_work is None:
            raise NotFound("来源作品不存在。")
        licensing.assert_remixable(source_work, user_id)

    # 2. Final safety pass over what will actually be public.
    from app.agents import safety

    verdict = safety.review(
        session,
        text=f"{title}\n{description or ''}",
        stage=ModerationStage.PRE_PUBLISH,
        subject_type="draft",
        subject_id=draft.id,
        user_id=user_id,
    )
    if verdict.status == ModerationStatus.REJECTED:
        raise ModerationRejected(verdict.public_message or "内容未通过安全检查。")

    # 3. Work and its immutable first version.
    work = Work(
        owner_user_id=user_id,
        visibility=visibility,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
    )
    session.add(work)
    session.flush()

    # Optional: the studio may have tagged this draft as an episode of a
    # series so it inherits the same cast. A standalone draft carries neither
    # key, and `assign_episode` is a no-op without a series_id.
    characters_service.assign_episode(
        session,
        user_id=user_id,
        work=work,
        series_id=draft.params_json.get("series_id"),
        episode_number=draft.params_json.get("episode_number"),
    )

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        description=description,
        cover_asset_id=cover_asset_id or draft.output_asset_id,
        primary_output_asset_id=draft.output_asset_id,
        ai_generated=True,
        generation_job_id=draft.latest_job_id,
        license_snapshot_id=draft.license_snapshot_id,
        reusable_params_json=_reusable_params(draft, visibility),
        immutable_created_at=utcnow(),
    )
    session.add(version)
    session.flush()
    work.current_version_id = version.id

    # 4. Media becomes readable to anyone who can see the work.
    for asset_id in {draft.output_asset_id, cover_asset_id} - {None}:
        asset = session.get(Asset, asset_id)
        if asset is not None and asset.owner_user_id == user_id:
            media_service.publish_asset(session, asset)

    _attach_tags(session, work, tags)

    # 5. The lineage edge. Without it a remix would lose its attribution.
    edge: LineageEdge | None = None
    if source_version is not None and draft.license_snapshot_id:
        source_work = session.get(Work, source_version.work_id)
        assert source_work is not None
        edge = lineage.create_edge(
            session,
            parent_version_id=source_version.id,
            child_version_id=version.id,
            parent_author_snapshot=licensing.author_snapshot(session, source_work),
            license_snapshot_id=draft.license_snapshot_id,
            workflow_version_id=version.workflow_version_id,
            reused_asset_ids=list(draft.params_json.get("reference_asset_ids", [])),
            created_by_user_id=user_id,
        )
        source_work.remix_count += 1

    # 6. Discovery index.
    search_service.index_version(session, work=work, version=version)

    # 7. Royalties, best-effort by design.
    royalties = _pay_royalties(session, user_id=user_id, draft=draft, version=version)

    # 8. Tell the ancestors.
    _notify_ancestors(session, version=version, actor_user_id=user_id, work=work)

    draft.published_work_id = work.id
    session.flush()
    return PublishOutcome(work=work, version=version, lineage_edge=edge, royalties=royalties)


def change_visibility(session: Session, *, user_id: str, work_id: str, visibility: str) -> Work:
    """Visibility changes are forward-only in effect.

    Revoking remix rights stops new derivatives but never invalidates existing
    ones, because their licence snapshots were frozen at creation time.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("不能修改他人的作品。")

    work.visibility = visibility
    session.flush()
    return work


def tombstone(
    session: Session, *, work_id: str, reason: str, actor_user_id: str | None = None
) -> Work:
    """Removes a work from circulation while keeping the chain intact.

    Descendants must still resolve their ancestry, so the row survives as a
    tombstone rather than being deleted.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")

    work.lifecycle_status = LifecycleStatus.TOMBSTONE
    work.tombstoned_at = utcnow()
    work.tombstone_reason = reason
    work.visibility = Visibility.PRIVATE
    session.flush()
    logger.info("work %s tombstoned by %s", work_id, actor_user_id or "system")
    return work


def hide(session: Session, *, work_id: str, reason: str, actor_user_id: str | None = None) -> Work:
    """Removes a work from discovery while leaving it fully restorable.

    Used both by the standalone `/works/{id}/hide` operator action and by a
    moderation `REJECTED` verdict on a `work` — a reviewer's call is always a
    judgement that can turn out wrong, so it must stay undoable via
    `restore()`, unlike the operator-only, terminal `tombstone()` above.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")

    work.lifecycle_status = LifecycleStatus.HIDDEN
    session.flush()
    logger.info("work %s hidden by %s: %s", work_id, actor_user_id or "system", reason)
    return work


def restore(session: Session, *, work_id: str) -> Work:
    """Undoes a hide. A tombstone is final and cannot be restored here."""
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.lifecycle_status == LifecycleStatus.TOMBSTONE:
        raise Conflict("墓碑作品不可恢复。")

    work.lifecycle_status = LifecycleStatus.ACTIVE
    session.flush()
    return work


def _reusable_params(draft: Draft, visibility: str) -> dict[str, Any]:
    """Only a remixable work exposes its parameters.

    Publishing view-only and still shipping the full prompt would make the
    licence meaningless.
    """
    if not Visibility(visibility).allows_remix:
        return {}
    params = dict(draft.params_json)
    params.pop("reference_asset_ids", None)
    # A remixer cannot use someone else's private character, so its id would
    # only 404 the next time it was resolved.
    params.pop("character_ids", None)
    params.pop("series_id", None)
    params.pop("episode_number", None)
    return params


def _attach_tags(session: Session, work: Work, tags: list[str]) -> None:
    for slug in {t.strip().lower() for t in tags if t.strip()}:
        tag = session.scalar(select(Tag).where(Tag.slug == slug))
        if tag is None:
            tag = Tag(slug=slug, label_zh=slug, label_en=slug, label_ja=slug)
            session.add(tag)
            session.flush()
        tag.usage_count += 1
        session.add(WorkTag(work_id=work.id, tag_id=tag.id))
    session.flush()


def _pay_royalties(
    session: Session, *, user_id: str, draft: Draft, version: WorkVersion
) -> list[dict[str, Any]]:
    if not config_service.is_enabled(session, "royalties"):
        return []

    config = config_service.get_typed(session, "royalty", RoyaltyConfig)
    rule = RoyaltyRule(
        enabled=config.enabled,
        first_level_rate_bps=config.first_level_rate_bps,
        decay_bps=config.decay_bps,
        max_levels=config.max_levels,
        min_payout=config.min_payout,
        total_cap_bps=config.total_cap_bps,
    )

    from app.models import GenerationJob

    base_amount = 0
    if draft.latest_job_id:
        job = session.get(GenerationJob, draft.latest_job_id)
        base_amount = (job.actual_credits or job.quoted_credits) if job else 0
    if base_amount <= 0:
        return []

    plans = distribute(
        session,
        payer_user_id=user_id,
        child_work_version_id=version.id,
        base_amount=base_amount,
        rule=rule,
        idempotency_key=f"royalty:{version.id}",
    )
    for plan in plans:
        notifications.notify(
            session,
            user_id=plan.beneficiary_user_id,
            type=NotificationType.ROYALTY_RECEIVED,
            title_key="notification.royalty_received",
            payload={"amount": plan.amount, "work_version_id": version.id},
            target_type="work_version",
            target_id=version.id,
        )
    return [
        {"beneficiary_user_id": p.beneficiary_user_id, "amount": p.amount, "level": p.level}
        for p in plans
    ]


def _notify_ancestors(
    session: Session, *, version: WorkVersion, actor_user_id: str, work: Work
) -> None:
    for edge in lineage.ancestors(session, version.id, limit=3):
        author_id = str(edge.parent_author_snapshot_json.get("user_id", ""))
        if not author_id or author_id == actor_user_id:
            continue
        notifications.notify(
            session,
            user_id=author_id,
            type=NotificationType.WORK_REMIXED,
            title_key="notification.work_remixed",
            payload={"work_id": work.id, "work_version_id": version.id},
            target_type="work",
            target_id=work.id,
        )
    session.flush()
