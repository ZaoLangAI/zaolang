"""Discovery, work detail, lineage and community interactions."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OptionalUser, rate_limited
from app.api.schemas.common import CountResponse, OkResponse, Page
from app.api.schemas.works import (
    AuthorSummary,
    LicenseInfo,
    LineageAncestor,
    LineageNodeResponse,
    LineageResponse,
    ReusableParams,
    TagResponse,
    VersionDiffEntry,
    VersionDiffResponse,
    VisibilityUpdateRequest,
    WorkDetail,
    WorkStats,
    WorkSummary,
    WorkVersionSummary,
)
from app.domain.errors import Conflict, NotFound
from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage_service
from app.domain.publishing import service as publishing
from app.domain.search import service as search_service
from app.models import (
    Bookmark,
    LicenseSnapshot,
    Like,
    LineageEdge,
    Profile,
    Tag,
    User,
    Work,
    WorkTag,
    WorkVersion,
)
from app.models.enums import ADMIN_ROLE_RANK, LifecycleStatus, Visibility
from app.presenters import media_urls

router = APIRouter(tags=["works"])


@router.get("/works", response_model=Page[WorkSummary])
def list_works(
    session: DbSession,
    viewer: OptionalUser,
    _: Annotated[None, Depends(rate_limited("public_read"))],
    q: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=64),
    remixable: bool = False,
    semantic: bool = True,
    sort: Literal["recent", "popular", "remixed"] = "recent",
    cursor: str | None = None,
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[WorkSummary]:
    if q:
        results = search_service.search(
            session, query=q, semantic=semantic, remixable_only=remixable, limit=limit + 1
        )
    else:
        results = search_service.browse(
            session, tag=tag, remixable_only=remixable, sort=sort, cursor=cursor, limit=limit + 1
        )

    has_more = len(results) > limit
    page = results[:limit]
    return Page(
        items=[_summary(session, r.work, r.version, viewer) for r in page],
        next_cursor=page[-1].work.id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/works/{work_id}", response_model=WorkDetail)
def get_work(
    work_id: str,
    session: DbSession,
    viewer: OptionalUser,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> WorkDetail:
    work, version = _load_visible(session, work_id, viewer)

    # View counting is intentionally not de-duplicated per user; the number is
    # a rough popularity signal, not an analytics metric.
    work.view_count += 1
    session.commit()

    summary = _summary(session, work, version, viewer)
    can_remix = licensing.can_remix(work, viewer.id if viewer else None)

    return WorkDetail(
        **summary.model_dump(),
        description=version.description,
        current_version=_version_summary(session, version),
        reusable_params=_reusable_params(version) if can_remix else None,
        license=_license_info(session, version),
        ancestors=_ancestors(session, version.id),
        descendant_count=len(lineage_service.descendants(session, version.id)),
        viewer_liked=_has_interaction(session, Like, viewer, work.id),
        viewer_bookmarked=_has_interaction(session, Bookmark, viewer, work.id),
        can_remix=can_remix,
        remix_block_reason=None if can_remix else "该作品仅用于展示，作者未开放二创。",
    )


@router.get("/works/{work_id}/lineage", response_model=LineageResponse)
def get_lineage(
    work_id: str,
    session: DbSession,
    viewer: OptionalUser,
    depth: int = Query(default=4, ge=1, le=8),
) -> LineageResponse:
    """Both directions in one payload.

    Tombstoned nodes stay in the graph so the chain is never visibly broken.
    """
    _work, version = _load_visible(session, work_id, viewer)
    tree = lineage_service.build_tree(session, version.id, max_depth=depth)
    all_descendants = lineage_service.descendants(session, version.id)

    return LineageResponse(
        root=_lineage_node(session, tree),
        ancestors=_ancestors(session, version.id),
        total_descendants=len(all_descendants),
        truncated=len(all_descendants) > _count_nodes(tree) - 1,
    )


@router.get("/works/{work_id}/similar", response_model=Page[WorkSummary])
def similar(
    work_id: str,
    session: DbSession,
    viewer: OptionalUser,
    limit: int = Query(default=8, ge=1, le=24),
) -> Page[WorkSummary]:
    _, version = _load_visible(session, work_id, viewer)
    results = search_service.similar_works(session, work_version_id=version.id, limit=limit)
    return Page(items=[_summary(session, r.work, r.version, viewer) for r in results])


@router.get("/work-versions/{child_version_id}/diff", response_model=VersionDiffResponse)
def version_diff(child_version_id: str, session: DbSession) -> VersionDiffResponse:
    """Field-by-field comparison against the parent version.

    Powers the "what changed" panel in the lineage graph.
    """
    edge = lineage_service.get_parent_edge(session, child_version_id)
    if edge is None:
        raise NotFound("该版本没有上游版本。")

    parent = session.get(WorkVersion, edge.parent_work_version_id)
    child = session.get(WorkVersion, child_version_id)
    if parent is None or child is None:
        raise NotFound("版本不存在。")

    parent_params = parent.reusable_params_json or {}
    child_params = child.reusable_params_json or {}
    entries = [
        VersionDiffEntry(
            field="title",
            parent_value=parent.title,
            child_value=child.title,
            changed=parent.title != child.title,
        )
    ]
    for key in sorted(set(parent_params) | set(child_params)):
        left = parent_params.get(key)
        right = child_params.get(key)
        entries.append(
            VersionDiffEntry(field=key, parent_value=left, child_value=right, changed=left != right)
        )

    return VersionDiffResponse(
        parent_work_version_id=parent.id, child_work_version_id=child.id, entries=entries
    )


@router.post("/works/{work_id}/like", response_model=CountResponse)
def like(work_id: str, user: CurrentUser, session: DbSession) -> CountResponse:
    work, _ = _load_visible(session, work_id, user)
    existing = session.scalar(select(Like).where(Like.user_id == user.id, Like.work_id == work_id))
    if existing is None:
        session.add(Like(user_id=user.id, work_id=work_id))
        work.like_count += 1
        session.commit()
    return CountResponse(count=work.like_count)


@router.delete("/works/{work_id}/like", response_model=CountResponse)
def unlike(work_id: str, user: CurrentUser, session: DbSession) -> CountResponse:
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    existing = session.scalar(select(Like).where(Like.user_id == user.id, Like.work_id == work_id))
    if existing is not None:
        session.delete(existing)
        work.like_count = max(0, work.like_count - 1)
        session.commit()
    return CountResponse(count=work.like_count)


@router.post("/works/{work_id}/bookmark", response_model=OkResponse)
def bookmark(work_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    _load_visible(session, work_id, user)
    existing = session.scalar(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.work_id == work_id)
    )
    if existing is None:
        session.add(Bookmark(user_id=user.id, work_id=work_id))
        session.commit()
    return OkResponse()


@router.delete("/works/{work_id}/bookmark", response_model=OkResponse)
def unbookmark(work_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    existing = session.scalar(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.work_id == work_id)
    )
    if existing is not None:
        session.delete(existing)
        session.commit()
    return OkResponse()


@router.patch("/works/{work_id}/visibility", response_model=WorkSummary)
def update_visibility(
    work_id: str, payload: VisibilityUpdateRequest, user: CurrentUser, session: DbSession
) -> WorkSummary:
    work = publishing.change_visibility(
        session, user_id=user.id, work_id=work_id, visibility=payload.visibility
    )
    session.commit()
    version = session.get(WorkVersion, work.current_version_id or "")
    if version is None:
        raise Conflict("作品没有可用版本。")
    return _summary(session, work, version, user)


@router.get("/tags", response_model=Page[TagResponse])
def list_tags(
    session: DbSession, limit: int = Query(default=40, ge=1, le=120)
) -> Page[TagResponse]:
    rows = session.scalars(select(Tag).order_by(Tag.usage_count.desc()).limit(limit))
    return Page(items=[TagResponse.model_validate(tag) for tag in rows])


# --- projections ---------------------------------------------------------


def _load_visible(session, work_id: str, viewer: User | None) -> tuple[Work, WorkVersion]:  # type: ignore[no-untyped-def]
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    is_staff = bool(viewer and any(r in ADMIN_ROLE_RANK for r in viewer.roles))
    licensing.assert_viewable(work, viewer.id if viewer else None, is_staff)

    version = session.get(WorkVersion, work.current_version_id or "")
    if version is None:
        raise NotFound("作品没有可用版本。")
    return work, version


def _summary(session, work: Work, version: WorkVersion, viewer: User | None) -> WorkSummary:  # type: ignore[no-untyped-def]
    return WorkSummary(
        id=work.id,
        title=version.title,
        visibility=Visibility(work.visibility),
        lifecycle_status=LifecycleStatus(work.lifecycle_status),
        cover_url=media_urls.asset_url(session, version.cover_asset_id),
        media_type=media_urls.media_type_of(session, version.primary_output_asset_id),
        author=_author(session, work.owner_user_id),
        stats=WorkStats(
            view_count=work.view_count,
            like_count=work.like_count,
            comment_count=work.comment_count,
            remix_count=work.remix_count,
        ),
        tags=_tags(session, work.id),
        remixable=licensing.can_remix(work, viewer.id if viewer else None),
        published_at=work.published_at,
    )


def _version_summary(session, version: WorkVersion) -> WorkVersionSummary:  # type: ignore[no-untyped-def]
    return WorkVersionSummary(
        id=version.id,
        version_number=version.version_number,
        title=version.title,
        description=version.description,
        cover_url=media_urls.asset_url(session, version.cover_asset_id),
        media_url=media_urls.asset_url(session, version.primary_output_asset_id),
        media_type=media_urls.media_type_of(session, version.primary_output_asset_id),
        ai_generated=version.ai_generated,
        created_at=version.immutable_created_at,
    )


def _author(session, user_id: str) -> AuthorSummary:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        return AuthorSummary(user_id=user_id, display_name="未知作者", handle=user_id)
    return AuthorSummary(
        user_id=user_id,
        display_name=profile.display_name,
        handle=profile.handle,
        avatar_url=media_urls.asset_url(session, profile.avatar_asset_id),
    )


def _tags(session, work_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    return list(
        session.scalars(
            select(Tag.slug)
            .join(WorkTag, WorkTag.tag_id == Tag.id)
            .where(WorkTag.work_id == work_id)
        )
    )


def _reusable_params(version: WorkVersion) -> ReusableParams:
    params = dict(version.reusable_params_json or {})
    return ReusableParams(
        prompt=params.pop("prompt", None),
        negative_prompt=params.pop("negative_prompt", None),
        seed=params.pop("seed", None),
        style_tags=params.pop("style_tags", []) or [],
        workflow_version_id=version.workflow_version_id,
        extra=params,
    )


def _license_info(session, version: WorkVersion) -> LicenseInfo | None:  # type: ignore[no-untyped-def]
    if not version.license_snapshot_id:
        return None
    snapshot = session.get(LicenseSnapshot, version.license_snapshot_id)
    if snapshot is None:
        return None
    return LicenseInfo(
        license_type=snapshot.license_type,
        attribution_text=snapshot.attribution_text,
        permissions=snapshot.permissions_json,
        captured_at=snapshot.captured_at,
    )


def _ancestors(session, version_id: str) -> list[LineageAncestor]:  # type: ignore[no-untyped-def]
    result: list[LineageAncestor] = []
    for depth, edge in enumerate(lineage_service.ancestors(session, version_id), start=1):
        parent = session.get(WorkVersion, edge.parent_work_version_id)
        if parent is None:
            continue
        parent_work = session.get(Work, parent.work_id)
        is_tombstone = (
            parent_work is not None and parent_work.lifecycle_status != LifecycleStatus.ACTIVE
        )
        snapshot = edge.parent_author_snapshot_json
        result.append(
            LineageAncestor(
                work_version_id=parent.id,
                work_id=parent.work_id,
                # The historical author credit survives even when the work does
                # not; only the content is withheld.
                title="" if is_tombstone else parent.title,
                author=AuthorSummary(
                    user_id=str(snapshot.get("user_id", "")),
                    display_name=str(snapshot.get("display_name", "未知作者")),
                    handle=str(snapshot.get("handle", "")),
                ),
                depth=depth,
                is_tombstone=is_tombstone,
                cover_url=None
                if is_tombstone
                else media_urls.asset_url(session, parent.cover_asset_id),
            )
        )
    return result


def _lineage_node(session, node) -> LineageNodeResponse:  # type: ignore[no-untyped-def]
    return LineageNodeResponse(
        work_version_id=node.work_version_id,
        work_id=node.work_id,
        title=node.title,
        author=node.author,
        depth=node.depth,
        is_tombstone=node.is_tombstone,
        cover_url=media_urls.asset_url(session, node.cover_asset_id),
        children=[_lineage_node(session, child) for child in node.children],
    )


def _count_nodes(node) -> int:  # type: ignore[no-untyped-def]
    return 1 + sum(_count_nodes(child) for child in node.children)


def _has_interaction(session, model, viewer: User | None, work_id: str) -> bool:  # type: ignore[no-untyped-def]
    if viewer is None:
        return False
    return (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.user_id == viewer.id, model.work_id == work_id)
        )
        or 0
    ) > 0


@router.get("/lineage-edges/{edge_id}", response_model=dict)
def get_edge(edge_id: str, session: DbSession) -> dict:
    edge = session.get(LineageEdge, edge_id)
    if edge is None:
        raise NotFound("创作链记录不存在。")
    return {
        "id": edge.id,
        "parent_work_version_id": edge.parent_work_version_id,
        "child_work_version_id": edge.child_work_version_id,
        "parent_author": edge.parent_author_snapshot_json,
        "depth": edge.depth,
        "created_at": edge.created_at,
    }
