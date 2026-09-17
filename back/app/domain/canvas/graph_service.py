"""The canvas graph: reads, writes, and the change feed behind them.

Three rules hold this together. They exist because two very different writers
share one canvas - a browser autosaving layout as someone drags cards, and a
Celery worker landing the output of a generation that started minutes ago.

**Rule 1 - the server never UPDATEs a node, it only INSERTs.**
An Agent result becomes a *new* card and a *new* edge. An INSERT carries no
`expected_revision`, so it cannot conflict with anything, and a generation
finishing at an arbitrary moment is harmless because it touches no row the
browser has ever seen. The corollary matters as much as the rule: an Agent's
live state must never live in `CanvasNode.data_json`, or client and server are
back to writing the same cell. It lives on `CanvasAgentRun` / `CanvasAgentTask`
and the client joins by id.

**Rule 2 - client writes are compare-and-set per node, and conflicts are per
operation.** `apply_ops` takes a batch; each op carries its own
`expected_revision`. A stale op is reported in `conflicts` and *the rest of the
batch still applies*. This is a deliberate break from `RevisionConflict`, which
the rest of this codebase raises for a whole-document CAS miss: rolling back
twenty accepted drags because a twenty-first card moved under one of them would
lose real work for no benefit.

**Rule 3 - one canvas-scoped sequence, allocated under the project row's
lock.** `_next_seq` serialises a client batch against a worker landing a
result, then hands each a disjoint range. Unlike the `revision` column it
replaces, *both writers succeed* - it orders writes, it never rejects one.
Every row stamps the `seq` it was written at, and every write also appends to
`canvas_changes`, which is what makes deletes visible to a `?since=N` reader:
a deleted row cannot carry its own tombstone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.domain.errors import ValidationFailed
from app.models import CanvasChange, CanvasEdge, CanvasNode, CanvasProject
from app.models.base import new_id
from app.models.enums import (
    CanvasChangeAction,
    CanvasChangeEntity,
    CanvasNodeKind,
    CanvasNodeOrigin,
)
from app.realtime import publisher

# A canvas is a working surface, not a document store. These caps exist for the
# same reason `document.py` caps the timeline: one runaway client must not be
# able to write a payload that later reads become unable to serve.
MAX_NODES = 2000
MAX_EDGES = 4000
# One batch is one autosave flush, not a whole session's history. A drag of a
# multi-selection is the realistic upper bound.
MAX_OPS_PER_BATCH = 200
# How far back `changes_since` will reconstruct. Beyond this a client is told
# to reload rather than being handed a partial history it would apply as if it
# were complete.
MAX_CHANGES_PER_READ = 500

_VALID_NODE_KINDS = frozenset(kind.value for kind in CanvasNodeKind)
# Positions are stored as integers; these bound what a client may claim so a
# stray `Infinity` or a 10^18 coordinate cannot be persisted.
_MAX_COORDINATE = 1_000_000
_MAX_DIMENSION = 20_000

# The size a server-inserted card is born at.
#
# A card the browser created gets its dimensions from React Flow's measurement
# on the next commit, but one inserted here never passes through that — it
# would stay NULL until somebody dragged it, and a card with no width renders
# at its content's natural size. For a picture card that means a generated
# image filling the entire viewport. This matches what a hand-added card
# settles at.
DEFAULT_RESULT_WIDTH = 240
DEFAULT_RESULT_HEIGHT = 230


class GraphOpError(ValidationFailed):
    """A single op was malformed. Malformed is not the same as stale: a stale
    op is data the client can reconcile, a malformed one is a client bug, so it
    fails the request rather than landing in `conflicts`."""


@dataclass(frozen=True, slots=True)
class OpConflict:
    op_id: str
    entity_id: str
    reason: Literal["stale_revision", "missing"]


@dataclass(frozen=True, slots=True)
class ApplyResult:
    change_seq: int
    applied: list[str]
    conflicts: list[OpConflict]
    changes: list[CanvasChange]


# --------------------------------------------------------------------------
# Sequence allocation
# --------------------------------------------------------------------------


def _next_seq(session: Session, canvas_id: str, count: int = 1) -> int:
    """Reserve `count` consecutive canvas-scoped sequence numbers.

    The `UPDATE ... RETURNING` takes the project row's lock, so a client op
    batch and a worker landing an agent result serialise here and receive
    disjoint ranges. The lock is held for microseconds and a canvas has a
    handful of writers at most.

    Returns the *first* number in the reserved range.
    """
    if count < 1:
        raise ValueError("count must be positive")
    row = session.execute(
        update(CanvasProject)
        .where(CanvasProject.id == canvas_id)
        .values(change_seq=CanvasProject.change_seq + count)
        .returning(CanvasProject.change_seq)
    ).first()
    if row is None:  # pragma: no cover - callers resolve the project first
        raise ValidationFailed("画布不存在。")
    end: int = row[0]
    return end - count + 1


def _log(
    session: Session,
    *,
    canvas_id: str,
    seq: int,
    entity_type: CanvasChangeEntity,
    entity_id: str,
    action: CanvasChangeAction,
    actor: str,
    actor_user_id: str | None,
    payload: dict[str, Any] | None = None,
) -> CanvasChange:
    change = CanvasChange(
        canvas_id=canvas_id,
        seq=seq,
        entity_type=entity_type.value,
        entity_id=entity_id,
        action=action.value,
        actor=actor,
        actor_user_id=actor_user_id,
        payload_json=payload or {},
    )
    session.add(change)
    return change


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def read_nodes(session: Session, canvas_id: str) -> list[CanvasNode]:
    return list(
        session.scalars(
            select(CanvasNode)
            .where(CanvasNode.canvas_id == canvas_id)
            .order_by(CanvasNode.seq, CanvasNode.id)
        )
    )


def read_edges(session: Session, canvas_id: str) -> list[CanvasEdge]:
    return list(
        session.scalars(
            select(CanvasEdge)
            .where(CanvasEdge.canvas_id == canvas_id)
            .order_by(CanvasEdge.seq, CanvasEdge.id)
        )
    )


def node_count(session: Session, canvas_id: str) -> int:
    """Counted in the database, not by materialising ids.

    This runs once per write batch and the cap it guards is 2000, so pulling
    every id back to call `len` on them is the difference between a number and
    a page of rows.
    """
    return (
        session.scalar(
            select(func.count()).select_from(CanvasNode).where(CanvasNode.canvas_id == canvas_id)
        )
        or 0
    )


def edge_count(session: Session, canvas_id: str) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(CanvasEdge).where(CanvasEdge.canvas_id == canvas_id)
        )
        or 0
    )


def bound_asset_ids(session: Session, canvas_id: str) -> set[str]:
    """Assets this canvas' cards point at.

    An index seek on `ix_canvas_nodes_canvas_id_binding_asset_id`, which is the
    reason `binding_asset_id` is a column: the previous shape had to scan every
    node's JSON in Python to answer this.
    """
    return set(
        session.scalars(
            select(CanvasNode.binding_asset_id).where(
                CanvasNode.canvas_id == canvas_id,
                CanvasNode.binding_asset_id.is_not(None),
            )
        )
    )


def bound_skill_ids(session: Session, canvas_id: str) -> set[str]:
    """Skills this canvas' cards point at.

    Same index-seek argument as `bound_asset_ids`. Note that what comes back
    is *claimed*, not authorised: node rows are client-written, so the caller
    still has to check that the viewer may see each of these skills before
    hydrating it.
    """
    return set(
        session.scalars(
            select(CanvasNode.binding_skill_id).where(
                CanvasNode.canvas_id == canvas_id,
                CanvasNode.binding_skill_id.is_not(None),
            )
        )
    )


def changes_since(
    session: Session, canvas_id: str, *, since: int, limit: int = MAX_CHANGES_PER_READ
) -> tuple[list[CanvasChange], bool]:
    """Changes after `since`, and whether the history has a gap.

    A gap means the caller asked for a point the feed can no longer
    reconstruct - either it fell out of the retention window, or more changes
    have accumulated than one read returns. Either way the honest answer is
    "reload", never a partial list the client would apply as if complete.
    """
    capped = min(limit, MAX_CHANGES_PER_READ)
    rows = list(
        session.scalars(
            select(CanvasChange)
            .where(CanvasChange.canvas_id == canvas_id, CanvasChange.seq > since)
            .order_by(CanvasChange.seq)
            .limit(capped + 1)
        )
    )
    if len(rows) > capped:
        return rows[:capped], True

    if since > 0 and rows:
        # The oldest surviving change is newer than the caller's cursor + 1, so
        # something between the two was pruned and the caller cannot be brought
        # up to date incrementally.
        oldest = session.scalar(
            select(CanvasChange.seq)
            .where(CanvasChange.canvas_id == canvas_id)
            .order_by(CanvasChange.seq)
            .limit(1)
        )
        if oldest is not None and oldest > since + 1:
            return [], True
    return rows, False


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _require_str(value: Any, field: str, *, max_length: int = 40) -> str:
    if not isinstance(value, str) or not value:
        raise GraphOpError(f"画布操作缺少 {field}。")
    if len(value) > max_length:
        raise GraphOpError(f"画布操作的 {field} 过长。")
    return value


def _coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphOpError(f"画布坐标 {field} 必须是数字。")
    if value != value or value in (float("inf"), float("-inf")):  # NaN / +-inf
        raise GraphOpError(f"画布坐标 {field} 不合法。")
    rounded = round(value)
    if abs(rounded) > _MAX_COORDINATE:
        raise GraphOpError(f"画布坐标 {field} 超出范围。")
    return rounded


def _dimension(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphOpError(f"画布尺寸 {field} 必须是数字。")
    rounded = round(value)
    if rounded < 1 or rounded > _MAX_DIMENSION:
        raise GraphOpError(f"画布尺寸 {field} 超出范围。")
    return rounded


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise GraphOpError(f"画布节点的 {field} 必须是对象。")
    return value


def _node_kind(value: Any) -> str:
    kind = _require_str(value, "node_kind", max_length=32)
    if kind not in _VALID_NODE_KINDS:
        raise GraphOpError(f"未知的画布节点类型：{kind}")
    return kind


def _binding_id(binding: dict[str, Any], key: str) -> str | None:
    """Lift an id out of the binding so it can be indexed.

    Kept as the single place this projection happens; anywhere else would let
    the columns and the JSON drift apart.
    """
    candidate = binding.get(key)
    return candidate if isinstance(candidate, str) and candidate else None


def _binding_columns(binding: dict[str, Any]) -> dict[str, str | None]:
    """The denormalised binding columns, always written as a set.

    Returned together rather than one at a time so that a `binding` swapped
    from a skill to an asset cannot leave the old column behind — which would
    keep hydrating a skill the card no longer points at.
    """
    return {
        "binding_asset_id": _binding_id(binding, "asset_id"),
        "binding_skill_id": _binding_id(binding, "skill_id"),
    }


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def node_payload(node: CanvasNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.node_kind,
        "position": {"x": node.position_x, "y": node.position_y},
        "size": (
            {"width": node.width, "height": node.height}
            if node.width is not None and node.height is not None
            else None
        ),
        "z_index": node.z_index,
        "binding": node.binding_json or None,
        "data": node.data_json or {},
        "origin": node.origin,
        "revision": node.revision,
    }


def edge_payload(edge: CanvasEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source_node_id,
        "target": edge.target_node_id,
        "source_handle": edge.source_handle or None,
        "target_handle": edge.target_handle or None,
        "kind": edge.edge_kind,
    }


def change_payload(change: CanvasChange) -> dict[str, Any]:
    return {
        "seq": change.seq,
        "entity_type": change.entity_type,
        "entity_id": change.entity_id,
        "action": change.action,
        "actor": change.actor,
        "payload": change.payload_json or {},
    }


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


def apply_ops(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    ops: list[dict[str, Any]],
) -> ApplyResult:
    """Apply a batch of client operations. See rules 2 and 3 above."""
    if len(ops) > MAX_OPS_PER_BATCH:
        raise GraphOpError(f"一次最多提交 {MAX_OPS_PER_BATCH} 个画布操作。")

    # Sequence numbers are allocated one per change, at the moment the change
    # is written, rather than reserved as a block up front. A block would have
    # to be sized by guesswork: a `node.delete` consumes one number per edge it
    # cascades, so any guess is wrong for a well-connected card, and overrunning
    # the block means issuing numbers a concurrent writer already holds.
    #
    # The cost of allocating per change is near zero: the first allocation takes
    # the project row's lock, and this transaction then holds it, so every later
    # one in the same batch is an uncontended update of a row already locked.

    applied: list[str] = []
    conflicts: list[OpConflict] = []
    changes: list[CanvasChange] = []

    existing_nodes = node_count(session, canvas_id)
    existing_edges = edge_count(session, canvas_id)

    for raw in ops:
        if not isinstance(raw, dict):
            raise GraphOpError("画布操作格式不合法。")
        op_id = _require_str(raw.get("op_id"), "op_id", max_length=64)
        kind = _require_str(raw.get("kind"), "kind", max_length=32)

        if kind == "node.create":
            if existing_nodes >= MAX_NODES:
                raise GraphOpError(f"画布节点不能超过 {MAX_NODES} 个。")
            created_node = _create_node(
                session,
                canvas_id=canvas_id,
                user_id=user_id,
                seq=_next_seq(session, canvas_id),
                payload=_json_object(raw.get("node"), "node"),
            )
            existing_nodes += 1
            changes.append(created_node)
            applied.append(op_id)

        elif kind == "node.update":
            updated = _update_node(
                session,
                canvas_id=canvas_id,
                user_id=user_id,
                op_id=op_id,
                raw=raw,
            )
            if isinstance(updated, OpConflict):
                conflicts.append(updated)
            else:
                changes.append(updated)
                applied.append(op_id)

        elif kind == "node.delete":
            removed = _delete_node(
                session,
                canvas_id=canvas_id,
                user_id=user_id,
                op_id=op_id,
                raw=raw,
            )
            if isinstance(removed, OpConflict):
                conflicts.append(removed)
            else:
                existing_nodes -= 1
                existing_edges -= len(removed) - 1
                changes.extend(removed)
                applied.append(op_id)

        elif kind == "edge.create":
            if existing_edges >= MAX_EDGES:
                raise GraphOpError(f"画布连线不能超过 {MAX_EDGES} 条。")
            created_edge = _create_edge(
                session,
                canvas_id=canvas_id,
                user_id=user_id,
                seq=_next_seq(session, canvas_id),
                payload=_json_object(raw.get("edge"), "edge"),
            )
            if created_edge is None:
                # The edge already exists. Creating it again is what the client
                # wanted the world to look like, so this is success, not a
                # conflict - the unique constraint made it idempotent for free.
                applied.append(op_id)
            else:
                existing_edges += 1
                changes.append(created_edge)
                applied.append(op_id)

        elif kind == "edge.delete":
            removed_edge = _delete_edge(
                session,
                canvas_id=canvas_id,
                user_id=user_id,
                edge_id=_require_str(raw.get("edge_id"), "edge_id"),
            )
            if removed_edge is not None:
                existing_edges -= 1
                changes.append(removed_edge)
            # Deleting an edge that is already gone is the outcome the client
            # asked for, so it reports as applied either way.
            applied.append(op_id)

        else:
            raise GraphOpError(f"未知的画布操作：{kind}")

    session.flush()
    current = session.scalar(select(CanvasProject.change_seq).where(CanvasProject.id == canvas_id))
    return ApplyResult(
        change_seq=current or 0,
        applied=applied,
        conflicts=conflicts,
        changes=changes,
    )


def _create_node(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    seq: int,
    payload: dict[str, Any],
) -> CanvasChange:
    position = _json_object(payload.get("position"), "position")
    size = _json_object(payload.get("size"), "size")
    binding = _json_object(payload.get("binding"), "binding")
    # The client mints node ids so a card is draggable the instant it appears,
    # before any round trip. Uniqueness is checked here rather than left to the
    # primary key: an IntegrityError surfaces as a 500 and takes the whole
    # batch with it, where a duplicate id is a client bug that deserves a
    # named 422.
    node_id = _require_str(payload.get("id"), "id")
    if session.get(CanvasNode, node_id) is not None:
        raise GraphOpError(f"画布节点 id 重复：{node_id}")
    node = CanvasNode(
        id=node_id,
        canvas_id=canvas_id,
        node_kind=_node_kind(payload.get("kind")),
        position_x=_coordinate(position.get("x"), "x"),
        position_y=_coordinate(position.get("y"), "y"),
        width=_dimension(size.get("width"), "width"),
        height=_dimension(size.get("height"), "height"),
        z_index=int(payload.get("z_index") or 0),
        **_binding_columns(binding),
        binding_json=binding,
        data_json=_json_object(payload.get("data"), "data"),
        origin=CanvasNodeOrigin.USER.value,
        revision=1,
        seq=seq,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    session.add(node)
    session.flush()
    return _log(
        session,
        canvas_id=canvas_id,
        seq=seq,
        entity_type=CanvasChangeEntity.NODE,
        entity_id=node.id,
        action=CanvasChangeAction.CREATED,
        actor="user",
        actor_user_id=user_id,
        payload=node_payload(node),
    )


def _update_node(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    op_id: str,
    raw: dict[str, Any],
) -> CanvasChange | OpConflict:
    node_id = _require_str(raw.get("node_id"), "node_id")
    expected = raw.get("expected_revision")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise GraphOpError("画布节点更新缺少 expected_revision。")

    # Allocated before the conditional UPDATE so the row and its change entry
    # carry the same number; a losing op simply never spends it.
    seq = _next_seq(session, canvas_id)
    values: dict[str, Any] = {
        "revision": CanvasNode.revision + 1,
        "seq": seq,
        "updated_by_user_id": user_id,
    }
    if "position" in raw:
        position = _json_object(raw.get("position"), "position")
        values["position_x"] = _coordinate(position.get("x"), "x")
        values["position_y"] = _coordinate(position.get("y"), "y")
    if "size" in raw:
        size = _json_object(raw.get("size"), "size")
        values["width"] = _dimension(size.get("width"), "width")
        values["height"] = _dimension(size.get("height"), "height")
    if "z_index" in raw:
        values["z_index"] = int(raw.get("z_index") or 0)
    if "binding" in raw:
        binding = _json_object(raw.get("binding"), "binding")
        values["binding_json"] = binding
        values.update(_binding_columns(binding))
    if "data" in raw:
        values["data_json"] = _json_object(raw.get("data"), "data")

    matched = rows_affected(
        session,
        update(CanvasNode)
        .where(
            CanvasNode.id == node_id,
            CanvasNode.canvas_id == canvas_id,
            CanvasNode.revision == expected,
        )
        .values(**values),
    )
    if matched != 1:
        # Either the card moved under this op or it is gone. Both are states
        # the client reconciles from the server row; neither fails the batch.
        node = session.get(CanvasNode, node_id)
        reason: Literal["stale_revision", "missing"] = (
            "stale_revision" if node is not None and node.canvas_id == canvas_id else "missing"
        )
        return OpConflict(op_id=op_id, entity_id=node_id, reason=reason)

    session.expire_all()
    node = session.get(CanvasNode, node_id)
    if node is None:  # pragma: no cover - the UPDATE just matched this row
        return OpConflict(op_id=op_id, entity_id=node_id, reason="missing")
    return _log(
        session,
        canvas_id=canvas_id,
        seq=seq,
        entity_type=CanvasChangeEntity.NODE,
        entity_id=node.id,
        action=CanvasChangeAction.UPDATED,
        actor="user",
        actor_user_id=user_id,
        payload=node_payload(node),
    )


def _delete_node(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    op_id: str,
    raw: dict[str, Any],
) -> list[CanvasChange] | OpConflict:
    """Delete a card and everything attached to it.

    The edge rows would go anyway - both endpoints are `ondelete=CASCADE`. But
    Postgres will not write the `canvas_changes` rows for them, so a client
    catching up by `?since=N` would never learn those edges vanished and would
    keep drawing lines to a card that is gone. The edges are therefore selected,
    deleted and logged explicitly here, before the node.
    """
    node_id = _require_str(raw.get("node_id"), "node_id")
    expected = raw.get("expected_revision")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise GraphOpError("画布节点删除缺少 expected_revision。")

    node = session.get(CanvasNode, node_id)
    if node is None or node.canvas_id != canvas_id:
        return OpConflict(op_id=op_id, entity_id=node_id, reason="missing")
    if node.revision != expected:
        return OpConflict(op_id=op_id, entity_id=node_id, reason="stale_revision")

    attached = list(
        session.scalars(
            select(CanvasEdge).where(
                CanvasEdge.canvas_id == canvas_id,
                (CanvasEdge.source_node_id == node_id) | (CanvasEdge.target_node_id == node_id),
            )
        )
    )

    changes: list[CanvasChange] = []
    for edge in attached:
        edge_id = edge.id
        session.delete(edge)
        changes.append(
            _log(
                session,
                canvas_id=canvas_id,
                seq=_next_seq(session, canvas_id),
                entity_type=CanvasChangeEntity.EDGE,
                entity_id=edge_id,
                action=CanvasChangeAction.DELETED,
                actor="user",
                actor_user_id=user_id,
            )
        )

    session.delete(node)
    changes.append(
        _log(
            session,
            canvas_id=canvas_id,
            seq=_next_seq(session, canvas_id),
            entity_type=CanvasChangeEntity.NODE,
            entity_id=node_id,
            action=CanvasChangeAction.DELETED,
            actor="user",
            actor_user_id=user_id,
        )
    )
    session.flush()
    return changes


def _create_edge(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    seq: int,
    payload: dict[str, Any],
) -> CanvasChange | None:
    source = _require_str(payload.get("source"), "source")
    target = _require_str(payload.get("target"), "target")
    if source == target:
        raise GraphOpError("画布连线不能连接同一个节点。")

    endpoints = set(
        session.scalars(
            select(CanvasNode.id).where(
                CanvasNode.canvas_id == canvas_id, CanvasNode.id.in_([source, target])
            )
        )
    )
    if len(endpoints) != 2:
        raise GraphOpError("画布连线指向了不存在的节点。")

    source_handle = payload.get("source_handle") or ""
    target_handle = payload.get("target_handle") or ""
    duplicate = session.scalar(
        select(CanvasEdge.id).where(
            CanvasEdge.canvas_id == canvas_id,
            CanvasEdge.source_node_id == source,
            CanvasEdge.target_node_id == target,
            CanvasEdge.source_handle == source_handle,
            CanvasEdge.target_handle == target_handle,
        )
    )
    if duplicate is not None:
        return None

    edge = CanvasEdge(
        id=payload.get("id") if isinstance(payload.get("id"), str) else new_id("cne"),
        canvas_id=canvas_id,
        source_node_id=source,
        target_node_id=target,
        source_handle=str(source_handle)[:40],
        target_handle=str(target_handle)[:40],
        edge_kind=str(payload.get("kind") or "link")[:32],
        seq=seq,
        created_by_user_id=user_id,
    )
    session.add(edge)
    session.flush()
    return _log(
        session,
        canvas_id=canvas_id,
        seq=seq,
        entity_type=CanvasChangeEntity.EDGE,
        entity_id=edge.id,
        action=CanvasChangeAction.CREATED,
        actor="user",
        actor_user_id=user_id,
        payload=edge_payload(edge),
    )


def _delete_edge(
    session: Session,
    *,
    canvas_id: str,
    user_id: str,
    edge_id: str,
) -> CanvasChange | None:
    matched = rows_affected(
        session,
        delete(CanvasEdge).where(CanvasEdge.id == edge_id, CanvasEdge.canvas_id == canvas_id),
    )
    if matched != 1:
        return None
    return _log(
        session,
        canvas_id=canvas_id,
        seq=_next_seq(session, canvas_id),
        entity_type=CanvasChangeEntity.EDGE,
        entity_id=edge_id,
        action=CanvasChangeAction.DELETED,
        actor="user",
        actor_user_id=user_id,
    )


# --------------------------------------------------------------------------
# Server-side writes (rule 1: insert only)
# --------------------------------------------------------------------------


def insert_agent_node(
    session: Session,
    *,
    canvas_id: str,
    node_kind: CanvasNodeKind,
    position: tuple[int, int],
    binding: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    source_node_id: str | None = None,
    actor_user_id: str | None = None,
) -> tuple[CanvasNode, list[CanvasChange]]:
    """Land a card the server produced, plus its edge from the agent card.

    Insert-only, per rule 1 - this is what lets a generation finishing at an
    arbitrary moment coexist with whatever the browser is doing. Callers are
    expected to have already checked `MAX_NODES` *before* spending the user's
    credits; failing here would mean a paid-for result with nowhere to land.
    """
    binding = binding or {}
    edges_needed = 1 if source_node_id else 0
    seq = _next_seq(session, canvas_id, count=1 + edges_needed)

    node = CanvasNode(
        canvas_id=canvas_id,
        node_kind=node_kind.value,
        position_x=position[0],
        position_y=position[1],
        width=DEFAULT_RESULT_WIDTH,
        height=DEFAULT_RESULT_HEIGHT,
        **_binding_columns(binding),
        binding_json=binding,
        data_json=data or {},
        origin=CanvasNodeOrigin.AGENT.value,
        revision=1,
        seq=seq,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    session.add(node)
    session.flush()

    changes = [
        _log(
            session,
            canvas_id=canvas_id,
            seq=seq,
            entity_type=CanvasChangeEntity.NODE,
            entity_id=node.id,
            action=CanvasChangeAction.CREATED,
            actor="agent",
            actor_user_id=actor_user_id,
            payload=node_payload(node),
        )
    ]

    if source_node_id:
        edge = CanvasEdge(
            canvas_id=canvas_id,
            source_node_id=source_node_id,
            target_node_id=node.id,
            edge_kind="generated",
            seq=seq + 1,
            created_by_user_id=actor_user_id,
        )
        session.add(edge)
        session.flush()
        changes.append(
            _log(
                session,
                canvas_id=canvas_id,
                seq=seq + 1,
                entity_type=CanvasChangeEntity.EDGE,
                entity_id=edge.id,
                action=CanvasChangeAction.CREATED,
                actor="agent",
                actor_user_id=actor_user_id,
                payload=edge_payload(edge),
            )
        )

    return node, changes


def publish_changes(canvas_id: str, frames: list[dict[str, Any]]) -> None:
    """Push already-committed changes to whoever is watching this canvas.

    Callers must pass frames built *before* `session.commit()` (the ORM rows
    expire on commit) and call this *after* it. Publishing from inside the
    transaction would announce writes that can still roll back, and a client
    that acted on one would render a card the database never kept.

    Delivery is best-effort. `CanvasChange` is the durable record, and every
    reconnect and every write carries a catch-up read, so a dropped frame costs
    latency rather than correctness.
    """
    for frame in frames:
        publisher.publish_canvas_change(canvas_id, frame)


def touch(session: Session, canvas_id: str) -> int:
    """Bump the sequence without writing a row. Used when only project-level
    metadata changed, so a listening client still learns to re-read it."""
    return _next_seq(session, canvas_id, count=1)


__all__ = [
    "DEFAULT_RESULT_HEIGHT",
    "DEFAULT_RESULT_WIDTH",
    "MAX_CHANGES_PER_READ",
    "MAX_EDGES",
    "MAX_NODES",
    "MAX_OPS_PER_BATCH",
    "ApplyResult",
    "GraphOpError",
    "OpConflict",
    "apply_ops",
    "bound_asset_ids",
    "bound_skill_ids",
    "change_payload",
    "changes_since",
    "edge_count",
    "edge_payload",
    "insert_agent_node",
    "node_count",
    "node_payload",
    "publish_changes",
    "read_edges",
    "read_nodes",
    "touch",
]
