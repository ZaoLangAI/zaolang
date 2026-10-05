"""A card's relation graph (P4): typed, directed edges between its looks /
scene variants, or between its images (`SkillAssetEdge`).

Invariants:

- Both ends are on the edge's own card (composite FKs) and on the same
  level; an edge never joins a look to an image.
- Each level is a DAG. `add_edge` takes the card row lock
  (`SELECT … FOR UPDATE` on `creation_skills`) before its cycle check, so two
  concurrent A→B / B→A inserts cannot both pass.
- Relations are valid for the card kind (`CHARACTER_RELATIONS` /
  `SCENE_RELATIONS`); `custom` needs a label. One edge per ordered pair.
- Owner-only metadata: edges are never published or moderated, so writing
  one does not withdraw a published card (unlike a look edit).
- `add_auto_edge` (job write-back, derive) never raises: a cycle, cap or
  duplicate is logged and skipped — it must not fail the job.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.errors import NotFound, ValidationFailed
from app.models import Asset, CreationSkill, GenerationJob, SkillAssetEdge, SkillAssetVariant
from app.models.base import utcnow
from app.models.enums import (
    CHARACTER_RELATIONS,
    SCENE_RELATIONS,
    AssetEdgeOrigin,
    AssetGraphLevel,
    AssetRelation,
    JobStatus,
)

logger = logging.getLogger(__name__)

MAX_EDGES_PER_SKILL = 2000
MAX_RELATIONS_PER_EDGE = 6
MAX_EDGE_LABEL_LEN = 40


def lock_card(session: Session, skill: CreationSkill) -> None:
    """Serialises graph writes on one card (the cycle check reads, then
    inserts)."""
    session.execute(select(CreationSkill.id).where(CreationSkill.id == skill.id).with_for_update())


def edges(session: Session, skill: CreationSkill, level: str | None = None) -> list[SkillAssetEdge]:
    stmt = select(SkillAssetEdge).where(SkillAssetEdge.skill_id == skill.id)
    if level is not None:
        stmt = stmt.where(SkillAssetEdge.level == level)
    return list(session.scalars(stmt.order_by(SkillAssetEdge.created_at, SkillAssetEdge.id)))


def endpoints(edge: SkillAssetEdge) -> tuple[str, str]:
    if edge.level == AssetGraphLevel.VARIANT:
        return str(edge.source_variant_id), str(edge.target_variant_id)
    return str(edge.source_entry_id), str(edge.target_entry_id)


def find_edge(session: Session, skill: CreationSkill, edge_id: str) -> SkillAssetEdge:
    edge = session.get(SkillAssetEdge, edge_id)
    if edge is None or edge.skill_id != skill.id:
        raise NotFound("关系不存在。")
    return edge


def _allowed_relations(skill: CreationSkill) -> frozenset[str]:
    return CHARACTER_RELATIONS if av.is_character(skill) else SCENE_RELATIONS


def _check_relations(
    skill: CreationSkill, relations: list[str], label: str | None
) -> tuple[list[str], str | None]:
    clean = list(dict.fromkeys(str(r) for r in relations))
    if not clean:
        raise ValidationFailed("至少选择一种关系。", fields={"relations": "不能为空"})
    if len(clean) > MAX_RELATIONS_PER_EDGE:
        raise ValidationFailed("关系类型过多。", fields={"relations": "过多"})
    allowed = _allowed_relations(skill)
    foreign = [r for r in clean if r not in allowed]
    if foreign:
        raise ValidationFailed(
            f"这张卡片不支持这些关系：{'、'.join(foreign)}。", fields={"relations": "不支持"}
        )
    text = (label or "").strip()[:MAX_EDGE_LABEL_LEN] or None
    if AssetRelation.CUSTOM in clean and not text:
        raise ValidationFailed("自定义关系需要填写名称。", fields={"label": "不能为空"})
    return clean, text


def _check_node(skill: CreationSkill, level: str, node_id: str, field: str) -> None:
    if level == AssetGraphLevel.VARIANT:
        found = av.find_variant(skill, node_id) is not None
    elif level == AssetGraphLevel.ENTRY:
        found = av.find_entry(skill, node_id) is not None
    else:
        raise ValidationFailed("关系层级无效。", fields={"level": "无效"})
    if not found:
        raise ValidationFailed("节点不在这张卡片上。", fields={field: "节点不存在"})


def _reaches(session: Session, skill: CreationSkill, level: str, start: str, goal: str) -> bool:
    """Whether `goal` is reachable from `start` along `level` edges."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges(session, skill, level):
        source, target = endpoints(edge)
        adjacency[source].append(target)
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            return True
        for nxt in adjacency[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def add_edge(
    session: Session,
    skill: CreationSkill,
    *,
    level: str,
    source_id: str,
    target_id: str,
    relations: list[str],
    label: str | None = None,
    origin: str = AssetEdgeOrigin.MANUAL,
    source_job_id: str | None = None,
) -> SkillAssetEdge:
    _check_node(skill, level, source_id, "source_id")
    _check_node(skill, level, target_id, "target_id")
    if source_id == target_id:
        raise ValidationFailed("不能连到自己。", fields={"target_id": "与起点相同"})
    clean, text = _check_relations(skill, relations, label)
    lock_card(session, skill)
    count = session.scalar(
        select(func.count()).select_from(SkillAssetEdge).where(SkillAssetEdge.skill_id == skill.id)
    )
    if (count or 0) >= MAX_EDGES_PER_SKILL:
        raise ValidationFailed(
            f"每张卡片最多 {MAX_EDGES_PER_SKILL} 条关系。", fields={"target_id": "数量已达上限"}
        )
    for edge in edges(session, skill, level):
        if endpoints(edge) == (source_id, target_id):
            raise ValidationFailed("这两个节点之间已有关系。", fields={"target_id": "关系已存在"})
    if _reaches(session, skill, level, target_id, source_id):
        raise ValidationFailed(
            "这条关系会形成环：终点已经能沿关系回到起点。", fields={"target_id": "会形成环"}
        )
    edge = SkillAssetEdge(
        skill_id=skill.id,
        level=level,
        relations_json=clean,
        label=text,
        origin=origin,
        source_job_id=source_job_id,
    )
    if level == AssetGraphLevel.VARIANT:
        edge.source_variant_id, edge.target_variant_id = source_id, target_id
    else:
        edge.source_entry_id, edge.target_entry_id = source_id, target_id
    session.add(edge)
    session.flush()
    return edge


def add_auto_edge(
    session: Session,
    skill: CreationSkill,
    *,
    level: str,
    source_id: str,
    target_id: str,
    relations: list[str],
    label: str | None = None,
    source_job_id: str | None = None,
) -> SkillAssetEdge | None:
    """`add_edge` for write-back and derive: skips (and logs) instead of
    raising, inside its own savepoint so a skip leaves the caller's work."""
    clean = [r for r in relations if r in _allowed_relations(skill)] or [AssetRelation.CUSTOM]
    if AssetRelation.CUSTOM in clean and not (label or "").strip():
        label = "派生"
    try:
        with session.begin_nested():
            return add_edge(
                session,
                skill,
                level=level,
                source_id=source_id,
                target_id=target_id,
                relations=clean,
                label=label,
                origin=AssetEdgeOrigin.AUTO,
                source_job_id=source_job_id,
            )
    except ValidationFailed as exc:
        logger.info(
            "auto edge skipped",
            extra={"skill_id": skill.id, "level": level, "reason": exc.message},
        )
        return None


def update_edge(
    session: Session,
    skill: CreationSkill,
    edge: SkillAssetEdge,
    *,
    relations: list[str] | None = None,
    label: str | None = None,
    clear_label: bool = False,
) -> SkillAssetEdge:
    next_relations = relations if relations is not None else list(edge.relations_json or [])
    next_label = None if clear_label else (label if label is not None else edge.label)
    clean, text = _check_relations(skill, next_relations, next_label)
    edge.relations_json = clean
    edge.label = text
    session.flush()
    return edge


def delete_edge(session: Session, skill: CreationSkill, edge: SkillAssetEdge) -> None:
    session.delete(edge)
    session.flush()


def relations_between(source: SkillAssetVariant, target: SkillAssetVariant) -> list[str]:
    """What differs between two looks / variants, as relation types — the
    edge a derive writes from the source look to the target. Empty when
    nothing the graph names differs."""
    sp, tp = source.presets_json or {}, target.presets_json or {}
    sa, ta = source.attributes_json or {}, target.attributes_json or {}
    found: list[str] = []
    if target.kind == "look":
        if sp.get("age_stage") != tp.get("age_stage"):
            found.append(AssetRelation.AGE)
        if sa.get("outfit") != ta.get("outfit") or (
            (source.description or "") != (target.description or "")
        ):
            found.append(AssetRelation.OUTFIT)
        if sa.get("state") != ta.get("state"):
            found.append(AssetRelation.EMOTION)
        if (source.scene_skill_id, source.scene_variant_id, sa.get("scene_note")) != (
            target.scene_skill_id,
            target.scene_variant_id,
            ta.get("scene_note"),
        ):
            found.append(AssetRelation.SCENE)
        if sp.get("period") != tp.get("period"):
            found.append(AssetRelation.PERIOD)
    else:
        for axis in ("lighting", "weather", "state", "period"):
            if sp.get(axis) != tp.get(axis):
                found.append(AssetRelation(axis))
    if (sa.get("custom") or []) != (ta.get("custom") or []):
        found.append(AssetRelation.CUSTOM)
    return [str(r) for r in found]


def link_job_output(
    session: Session,
    skill: CreationSkill,
    *,
    asset_id: str,
    params: dict[str, Any],
    job_id: str,
) -> SkillAssetEdge | None:
    """After write-back filed `asset_id` from a job with `source_entry_id`
    (P6): the image-level auto edge source → new image. An adjust is an
    `edit` labelled with its instruction; a derive names what differs
    between the two looks (`relations_between`), `scene` for a character
    placed in its scene. Skips (logs) when either image is gone."""
    source_id = params.get("source_entry_id")
    if not source_id:
        return None
    source = av.find_entry(skill, str(source_id))
    target = next(
        (
            entry
            for entry in reversed(av.entries(skill))
            if entry.asset_id == asset_id and entry.source_job_id == job_id
        ),
        None,
    )
    if source is None or target is None or source.id == target.id:
        logger.info("job output edge skipped", extra={"job_id": job_id, "skill_id": skill.id})
        return None
    label: str | None = None
    if params.get("asset_edit"):
        relations: list[str] = [AssetRelation.EDIT]
        label = str(params.get("prompt") or "").strip()[:MAX_EDGE_LABEL_LEN] or None
    else:
        relations = relations_between(source.variant, target.variant)
        if params.get("asset_output_mode") == "in_scene" and AssetRelation.SCENE not in relations:
            relations.append(AssetRelation.SCENE)
    return add_auto_edge(
        session,
        skill,
        level=AssetGraphLevel.ENTRY,
        source_id=source.id,
        target_id=target.id,
        relations=relations,
        label=label,
        source_job_id=job_id,
    )


ACTIVE_JOB_STATUSES = (
    JobStatus.CREATED,
    JobStatus.QUEUED,
    JobStatus.SUBMITTED,
    JobStatus.RUNNING,
    JobStatus.AWAITING_INPUT,
)
PENDING_WINDOW = dt.timedelta(hours=2)


def pending_jobs(session: Session, skill: CreationSkill) -> list[dict[str, Any]]:
    """The owner's still-running jobs filing into this card (last two
    hours) — the graph's placeholder nodes."""
    key = "target_character_id" if av.is_character(skill) else "target_scene_id"
    rows = session.scalars(
        select(GenerationJob)
        .where(
            GenerationJob.user_id == skill.owner_user_id,
            GenerationJob.status.in_([status.value for status in ACTIVE_JOB_STATUSES]),
            GenerationJob.created_at >= utcnow() - PENDING_WINDOW,
            GenerationJob.request_json[key].astext == skill.id,
        )
        .order_by(GenerationJob.created_at)
        .limit(50)
    ).all()
    return [
        {
            "job_id": job.id,
            "status": job.status,
            "mode": "edit"
            if job.request_json.get("asset_edit")
            else job.request_json.get("asset_output_mode")
            or ("derive" if job.request_json.get("source_entry_id") else None),
            "target_variant_id": job.request_json.get("target_variant_id"),
            "source_entry_id": job.request_json.get("source_entry_id"),
        }
        for job in rows
    ]


@dataclass(frozen=True, slots=True)
class CardGraph:
    skill: CreationSkill
    variants: list[SkillAssetVariant]
    edges: list[SkillAssetEdge]
    pending: list[dict[str, Any]]


def graph(session: Session, skill: CreationSkill) -> CardGraph:
    """Everything the management page draws, in one read. Warms the
    identity map with every entry's `Asset` first — signing a URL looks the
    asset up, and a 480-image card must not do that one query at a time."""
    variants = av.variants(skill)
    asset_ids = {entry.asset_id for variant in variants for entry in variant.entries}
    if asset_ids:
        session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
    return CardGraph(
        skill=skill,
        variants=variants,
        edges=edges(session, skill),
        pending=pending_jobs(session, skill),
    )
