"""Creative chain: edges, traversal and tombstone resolution.

Lineage is stored per *version*, not per work, so editing or hiding a parent can
never rewrite what a descendant inherited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, NotFound
from app.models import LineageEdge, Work, WorkVersion
from app.models.base import utcnow
from app.models.enums import LifecycleStatus

MAX_TRAVERSAL_DEPTH = 24


@dataclass(slots=True)
class LineageNode:
    work_version_id: str
    work_id: str
    title: str
    author: dict[str, Any]
    depth: int
    is_tombstone: bool
    cover_asset_id: str | None = None
    license_type: str | None = None
    children: list[LineageNode] = field(default_factory=list)


def create_edge(
    session: Session,
    *,
    parent_version_id: str,
    child_version_id: str,
    parent_author_snapshot: dict[str, Any],
    license_snapshot_id: str,
    workflow_version_id: str | None,
    reused_asset_ids: list[str],
    created_by_user_id: str,
) -> LineageEdge:
    """Creates the single edge that binds a remix to its source.

    Depth is materialised from the parent so ancestor walks and royalty
    distribution do not need a recursive query on the hot path.
    """
    existing = session.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == child_version_id)
    )
    if existing is not None:
        raise Conflict("该版本已存在创作链记录。")

    parent_edge = session.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == parent_version_id)
    )
    depth = (parent_edge.depth + 1) if parent_edge else 1

    edge = LineageEdge(
        parent_work_version_id=parent_version_id,
        child_work_version_id=child_version_id,
        parent_author_snapshot_json=parent_author_snapshot,
        license_snapshot_id=license_snapshot_id,
        workflow_version_id=workflow_version_id,
        reused_asset_ids_json=list(reused_asset_ids),
        depth=depth,
        created_by_user_id=created_by_user_id,
        created_at=utcnow(),
    )
    session.add(edge)
    session.flush()
    return edge


def get_parent_edge(session: Session, child_version_id: str) -> LineageEdge | None:
    return session.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == child_version_id)
    )


def ancestors(
    session: Session, version_id: str, limit: int = MAX_TRAVERSAL_DEPTH
) -> list[LineageEdge]:
    """Walks from a version up to the original, nearest ancestor first."""
    chain: list[LineageEdge] = []
    cursor = version_id
    seen: set[str] = set()
    while len(chain) < limit:
        edge = get_parent_edge(session, cursor)
        if edge is None or edge.parent_work_version_id in seen:
            break
        chain.append(edge)
        seen.add(edge.parent_work_version_id)
        cursor = edge.parent_work_version_id
    return chain


def descendants(
    session: Session, version_id: str, limit: int = MAX_TRAVERSAL_DEPTH
) -> list[LineageEdge]:
    """Breadth-first walk over everything derived from a version."""
    collected: list[LineageEdge] = []
    frontier = [version_id]
    seen: set[str] = {version_id}
    depth = 0
    while frontier and depth < limit:
        edges = list(
            session.scalars(
                select(LineageEdge).where(LineageEdge.parent_work_version_id.in_(frontier))
            )
        )
        if not edges:
            break
        collected.extend(edges)
        frontier = [e.child_work_version_id for e in edges if e.child_work_version_id not in seen]
        seen.update(frontier)
        depth += 1
    return collected


def _node_for_version(session: Session, version_id: str, depth: int) -> LineageNode | None:
    version = session.get(WorkVersion, version_id)
    if version is None:
        return None
    work = session.get(Work, version.work_id)
    if work is None:
        return None
    is_tombstone = work.lifecycle_status != LifecycleStatus.ACTIVE
    return LineageNode(
        work_version_id=version.id,
        work_id=work.id,
        # A hidden or tombstoned ancestor keeps its slot in the chain but stops
        # exposing its content; the historical author credit is preserved.
        title="" if is_tombstone else version.title,
        author={},
        depth=depth,
        is_tombstone=is_tombstone,
        cover_asset_id=None if is_tombstone else version.cover_asset_id,
    )


def build_tree(session: Session, root_version_id: str, max_depth: int = 6) -> LineageNode:
    """Builds the downstream tree used by the lineage graph view."""
    root = _node_for_version(session, root_version_id, 0)
    if root is None:
        raise NotFound("作品版本不存在。")

    index: dict[str, LineageNode] = {root_version_id: root}
    frontier = [root_version_id]
    depth = 0
    while frontier and depth < max_depth:
        edges = list(
            session.scalars(
                select(LineageEdge).where(LineageEdge.parent_work_version_id.in_(frontier))
            )
        )
        if not edges:
            break
        next_frontier: list[str] = []
        for edge in edges:
            child = _node_for_version(session, edge.child_work_version_id, depth + 1)
            if child is None:
                continue
            child.author = dict(edge.parent_author_snapshot_json)
            parent = index.get(edge.parent_work_version_id)
            if parent is not None:
                parent.children.append(child)
            index[child.work_version_id] = child
            next_frontier.append(child.work_version_id)
        frontier = next_frontier
        depth += 1
    return root


def is_referenced_by_descendants(session: Session, version_id: str) -> bool:
    return (
        session.scalar(
            select(LineageEdge.id).where(LineageEdge.parent_work_version_id == version_id).limit(1)
        )
        is not None
    )


def ancestor_author_ids(session: Session, version_id: str, max_levels: int) -> list[str]:
    """Ancestor authors nearest-first, deduplicated, excluding self-references.

    Feeds royalty distribution: an author never pays royalties to themselves,
    and each distinct ancestor is paid at most once per publication.
    """
    result: list[str] = []
    seen: set[str] = set()
    for edge in ancestors(session, version_id, limit=max_levels):
        author_id = str(edge.parent_author_snapshot_json.get("user_id", ""))
        if author_id and author_id not in seen:
            seen.add(author_id)
            result.append(author_id)
        if len(result) >= max_levels:
            break
    return result
