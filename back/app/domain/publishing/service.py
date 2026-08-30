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

from app.domain.access import service as access_service
from app.domain.audit import service as audit
from app.domain.credits.royalty import RoyaltyRule, distribute
from app.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    ModerationRejected,
    NotFound,
    ValidationFailed,
)
from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage
from app.domain.media import service as media_service
from app.domain.moderation_policy import match_blocked_keyword, record_block_signal
from app.domain.moderation_queue import service as moderation_queue
from app.domain.notifications import push as notifications
from app.domain.search import service as search_service
from app.models import (
    Asset,
    Draft,
    GenerationJob,
    LicenseSnapshot,
    LineageEdge,
    Profile,
    Tag,
    User,
    Work,
    WorkAppeal,
    WorkTag,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    DraftPublishStatus,
    LifecycleStatus,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import ContentModerationConfig, RoyaltyConfig

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
        licensing.assert_remixable(work, user_id, session)

        version = session.get(WorkVersion, work.current_version_id or "")
        if version is None:
            raise NotFound("来源作品没有可用版本。")

        snapshot = licensing.capture_license_snapshot(
            session, source_version=version, work=work, remixer_user_id=user_id
        )
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
    _maybe_link_draft_to_episode(session, user_id=user_id, draft=draft)
    return draft


def _maybe_link_draft_to_episode(session: Session, *, user_id: str, draft: Draft) -> None:
    """Best-effort `candidate` content-link when the studio jump-out set
    `params.link_episode_id`. A missing/foreign episode must not roll the
    draft back — the content-link list is a convenience view."""
    episode_id = draft.params_json.get("link_episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        return
    from app.domain.editor import service as editor_service

    editor_service.maybe_link_draft(
        session, user_id=user_id, episode_id=episode_id, draft_id=draft.id
    )


def request_publish(
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
    access_credits: int = 0,
) -> Draft:
    """Accepts a publish intent. The eight-step transaction runs in a worker.

    Keyword blocks stay synchronous so obvious refusals do not occupy a queue
    slot. The LLM safety pass is the part that used to hold the HTTP request.
    """
    draft = _owned_unpublished_draft(session, user_id=user_id, draft_id=draft_id)
    if draft.publish_status == DraftPublishStatus.PENDING:
        raise Conflict("该草稿正在审核发布中。")
    if draft.output_asset_id is None:
        raise ValidationFailed("草稿还没有生成结果，无法发布。")
    if not rights_confirmed:
        raise ValidationFailed(
            "请先确认你拥有所有新增素材的使用权。", fields={"rights_confirmed": "必须勾选"}
        )

    _assert_source_still_remixable(session, draft, user_id)
    _reject_blocked_keywords(session, title=title, description=description, user_id=user_id)

    draft.title = title
    draft.description = description
    draft.publish_status = DraftPublishStatus.PENDING
    draft.publish_failure_message = None
    draft.publish_params_json = {
        "visibility": visibility,
        "tags": list(tags),
        "cover_asset_id": cover_asset_id,
        "access_credits": access_credits,
        "rights_confirmed": True,
    }
    session.flush()
    return draft


def enqueue_draft_publish(draft_id: str) -> None:
    from app.workers import tasks

    tasks.run_draft_publish.delay(draft_id)


def revert_publish_request(session: Session, draft: Draft) -> None:
    """Clears a pending accept when the worker message could not be queued."""
    draft.publish_status = None
    draft.publish_params_json = {}
    draft.publish_failure_message = None
    session.flush()


def finalize_draft_publish(session: Session, draft_id: str) -> None:
    """Worker body: safety then the remaining publish steps, then notify.

    Idempotent. A draft that already has a work only re-sends the success
    notification. A rejected (or never-submitted) draft is a no-op so a
    redelivered message cannot recreate a work after the author was told no.
    """
    draft = session.get(Draft, draft_id)
    if draft is None:
        logger.warning("draft publish skipped: %s is gone", draft_id)
        return
    if draft.published_work_id is not None:
        _notify_author_published(session, draft)
        return
    if draft.publish_status != DraftPublishStatus.PENDING:
        return

    params = dict(draft.publish_params_json or {})
    title = draft.title or ""
    if not title.strip():
        _mark_publish_rejected(session, draft, "标题不能为空。")
        return

    cover = params.get("cover_asset_id")
    cover_asset_id = cover if isinstance(cover, str) and cover else None
    raw_tags = params.get("tags") or []
    tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []

    try:
        publish(
            session,
            user_id=draft.user_id,
            draft_id=draft.id,
            title=title,
            description=draft.description,
            visibility=str(params.get("visibility") or Visibility.PUBLIC_VIEW_ONLY),
            tags=tags,
            cover_asset_id=cover_asset_id,
            rights_confirmed=True,
            access_credits=int(params.get("access_credits") or 0),
        )
    except ModerationRejected as exc:
        _mark_publish_rejected(session, draft, exc.message)
        return
    except Conflict:
        session.refresh(draft)
        if draft.published_work_id is not None:
            _notify_author_published(session, draft)
            return
        raise
    except DomainError as exc:
        _mark_publish_rejected(session, draft, exc.message)
        return

    _notify_author_published(session, draft)


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
    access_credits: int = 0,
) -> PublishOutcome:
    draft = _owned_unpublished_draft(session, user_id=user_id, draft_id=draft_id)
    if draft.output_asset_id is None:
        raise ValidationFailed("草稿还没有生成结果，无法发布。")
    if not rights_confirmed:
        raise ValidationFailed(
            "请先确认你拥有所有新增素材的使用权。", fields={"rights_confirmed": "必须勾选"}
        )

    # 1. The source may have been locked down since the draft was created.
    source_version = _assert_source_still_remixable(session, draft, user_id)

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
    priced = access_service.normalize_access_credits(session, access_credits, actor_user_id=user_id)
    if not Visibility(visibility).allows_remix:
        priced = 0
    work = Work(
        owner_user_id=user_id,
        visibility=visibility,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
        access_credits=priced,
    )
    session.add(work)
    session.flush()

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
        editor_export_id=draft.editor_export_id,
    )
    session.add(version)
    session.flush()
    work.current_version_id = version.id

    if verdict.status == ModerationStatus.NEEDS_REVIEW:
        # Uncertain rather than unsafe: the work still goes live (an
        # indefinite hold with no queue to clear it would just be a silent
        # block by another name), but a reviewer now has a real row to act
        # on instead of the verdict being recorded and never followed up on.
        moderation_queue.enqueue_for_review(
            session,
            subject_type="work",
            subject_id=work.id,
            stage=ModerationStage.PRE_PUBLISH,
            reason_code=verdict.reason_code,
            categories=verdict.categories_json.get("categories"),
        )

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
    draft.publish_status = None
    draft.publish_failure_message = None
    session.flush()
    return PublishOutcome(work=work, version=version, lineage_edge=edge, royalties=royalties)


def change_visibility(
    session: Session,
    *,
    user_id: str,
    work_id: str,
    visibility: str,
    access_credits: int | None = None,
) -> Work:
    """Visibility changes are forward-only in effect.

    Revoking remix rights stops new derivatives but never invalidates existing
    ones, because their licence snapshots were frozen at creation time.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("不能修改他人的作品。")
    if work.lifecycle_status in {LifecycleStatus.TRASHED, LifecycleStatus.TOMBSTONE}:
        raise Conflict("回收站或墓碑作品不能修改可见性。")

    work.visibility = visibility
    if not Visibility(visibility).allows_remix:
        work.access_credits = 0
    elif access_credits is not None:
        work.access_credits = access_service.normalize_access_credits(
            session, access_credits, actor_user_id=user_id
        )
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
    work.trashed_at = None
    work.visibility_before_trash = None
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
    work.hide_reason = reason
    session.flush()
    logger.info("work %s hidden by %s: %s", work_id, actor_user_id or "system", reason)
    return work


def restore(session: Session, *, work_id: str) -> Work:
    """Undoes a hide. A tombstone is final and cannot be restored here."""
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.lifecycle_status in {LifecycleStatus.TOMBSTONE, LifecycleStatus.TRASHED}:
        raise Conflict("墓碑或回收站作品不能从这里恢复。")

    work.lifecycle_status = LifecycleStatus.ACTIVE
    work.hide_reason = None
    session.flush()
    return work


def trash(session: Session, *, user_id: str, work_id: str) -> Work:
    """Moves a published work into the owner's recycle bin."""
    work = _owned_work(session, user_id=user_id, work_id=work_id)
    if work.lifecycle_status == LifecycleStatus.TOMBSTONE:
        raise Conflict("墓碑作品不能移入回收站。")
    if work.lifecycle_status == LifecycleStatus.TRASHED:
        raise Conflict("作品已在回收站中。")

    work.visibility_before_trash = work.visibility
    work.visibility = Visibility.PRIVATE
    work.lifecycle_status = LifecycleStatus.TRASHED
    work.trashed_at = utcnow()
    session.flush()
    logger.info("work %s moved to trash by %s", work_id, user_id)
    return work


def untrash(session: Session, *, user_id: str, work_id: str) -> Work:
    """Restores a trashed work to active with its previous visibility."""
    work = _owned_work(session, user_id=user_id, work_id=work_id)
    if work.lifecycle_status != LifecycleStatus.TRASHED:
        raise Conflict("只有回收站中的作品可以恢复。")

    work.lifecycle_status = LifecycleStatus.ACTIVE
    work.visibility = work.visibility_before_trash or Visibility.PUBLIC_VIEW_ONLY
    work.visibility_before_trash = None
    work.trashed_at = None
    work.hide_reason = None
    session.flush()
    logger.info("work %s restored from trash by %s", work_id, user_id)
    return work


def purge(session: Session, *, user_id: str, work_id: str) -> str:
    """Permanently removes a trashed work.

    Unreferenced works are hard-deleted with their exclusive media. Referenced
    works become tombstones so descendants keep a lineage slot, but exclusive
    cover/output files are still purged.
    """
    work = _owned_work(session, user_id=user_id, work_id=work_id)
    if work.lifecycle_status != LifecycleStatus.TRASHED:
        raise Conflict("只有回收站中的作品可以彻底删除。")

    referenced = _is_referenced(session, work)
    asset_ids = _version_media_ids(session, work.id)
    actor = session.get(User, user_id)

    if referenced:
        _detach_version_media(session, work.id)
        tombstone(session, work_id=work_id, reason="author_purged", actor_user_id=user_id)
        media_service.delete_exclusive_assets(session, asset_ids=asset_ids, except_work_id=work_id)
        audit.record(
            session,
            actor=actor,
            action="work.purge",
            target_type="work",
            target_id=work_id,
            before={"lifecycle_status": LifecycleStatus.TRASHED, "referenced": True},
            after={"lifecycle_status": LifecycleStatus.TOMBSTONE},
            reason="author_purged",
        )
        logger.info("work %s purged to tombstone by %s", work_id, user_id)
        return "tombstone"

    for appeal in session.scalars(select(WorkAppeal).where(WorkAppeal.work_id == work_id)):
        session.delete(appeal)
    for draft in session.scalars(select(Draft).where(Draft.published_work_id == work_id)):
        session.delete(draft)
    work.current_version_id = None
    session.flush()
    for version in list(session.scalars(select(WorkVersion).where(WorkVersion.work_id == work_id))):
        session.delete(version)
    session.flush()

    media_service.delete_exclusive_assets(session, asset_ids=asset_ids, except_work_id=work_id)
    session.delete(work)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="work.purge",
        target_type="work",
        target_id=work_id,
        before={"lifecycle_status": LifecycleStatus.TRASHED, "referenced": False},
        after={"deleted": True},
        reason="author_purged",
    )
    logger.info("work %s hard-deleted by %s", work_id, user_id)
    return "deleted"


def work_is_referenced(session: Session, work: Work) -> bool:
    return _is_referenced(session, work)


def _owned_unpublished_draft(session: Session, *, user_id: str, draft_id: str) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise NotFound("草稿不存在。")
    if draft.user_id != user_id:
        raise Forbidden("不能发布他人的草稿。")
    if draft.published_work_id is not None:
        raise Conflict("该草稿已经发布。")
    return draft


def _assert_source_still_remixable(
    session: Session, draft: Draft, user_id: str
) -> WorkVersion | None:
    if not draft.source_work_version_id:
        return None
    source_version = session.get(WorkVersion, draft.source_work_version_id)
    if source_version is None:
        raise NotFound("来源版本不存在。")
    source_work = session.get(Work, source_version.work_id)
    if source_work is None:
        raise NotFound("来源作品不存在。")
    licensing.assert_source_still_remixable(source_work, user_id)
    return source_version


def _reject_blocked_keywords(
    session: Session,
    *,
    title: str,
    description: str | None,
    user_id: str,
) -> None:
    config = config_service.get_typed(session, "content_moderation", ContentModerationConfig)
    if not match_blocked_keyword([title, description or ""], config.blocked_keywords):
        return
    record_block_signal(config_key="content_moderation", subject_type="draft", user_id=user_id)
    raise ModerationRejected("内容未通过安全检查，请调整描述后重试。")


def _mark_publish_rejected(session: Session, draft: Draft, message: str) -> None:
    draft.publish_status = DraftPublishStatus.REJECTED
    draft.publish_failure_message = message
    session.flush()
    _notify_author_rejected(session, draft, message)


def _notify_author_published(session: Session, draft: Draft) -> None:
    notifications.sync_draft_publish_notification(
        session,
        draft=draft,
        published=True,
        work_id=draft.published_work_id,
    )


def _notify_author_rejected(session: Session, draft: Draft, message: str) -> None:
    notifications.sync_draft_publish_notification(
        session,
        draft=draft,
        published=False,
        public_message=message,
    )


def _owned_work(session: Session, *, user_id: str, work_id: str) -> Work:
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("不能操作他人的作品。")
    return work


def _is_referenced(session: Session, work: Work) -> bool:
    version_ids = list(
        session.scalars(select(WorkVersion.id).where(WorkVersion.work_id == work.id))
    )
    if not version_ids:
        return False
    return any(
        session.scalar(select(model.id).where(column.in_(version_ids)).limit(1))
        for model, column in (
            (LineageEdge, LineageEdge.parent_work_version_id),
            (Draft, Draft.source_work_version_id),
            (LicenseSnapshot, LicenseSnapshot.source_work_version_id),
            (GenerationJob, GenerationJob.source_work_version_id),
        )
    )


def _version_media_ids(session: Session, work_id: str) -> list[str]:
    ids: list[str] = []
    for cover_id, output_id in session.execute(
        select(WorkVersion.cover_asset_id, WorkVersion.primary_output_asset_id).where(
            WorkVersion.work_id == work_id
        )
    ):
        if cover_id:
            ids.append(cover_id)
        if output_id:
            ids.append(output_id)
    return ids


def _detach_version_media(session: Session, work_id: str) -> None:
    for version in session.scalars(select(WorkVersion).where(WorkVersion.work_id == work_id)):
        version.cover_asset_id = None
        version.primary_output_asset_id = None
    session.flush()


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
    config = config_service.get_typed(session, "royalty", RoyaltyConfig)
    if not config.enabled:
        return []
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
    work = session.get(Work, version.work_id)
    for plan in plans:
        notifications.notify(
            session,
            user_id=plan.beneficiary_user_id,
            type=NotificationType.ROYALTY_RECEIVED,
            title_key="notification.royalty_received",
            payload={
                "amount": plan.amount,
                "work_id": version.work_id,
                "work_version_id": version.id,
                "work_title": version.title,
            },
            target_type="work",
            target_id=version.work_id if work is not None else version.id,
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
        profile = session.scalar(select(Profile).where(Profile.user_id == author_id))
        if profile is not None and not profile.notify_on_remix:
            continue
        notifications.notify(
            session,
            user_id=author_id,
            type=NotificationType.WORK_REMIXED,
            title_key="notification.work_remixed",
            payload={
                "work_id": work.id,
                "work_version_id": version.id,
                "work_title": version.title,
            },
            target_type="work",
            target_id=work.id,
        )
    session.flush()
