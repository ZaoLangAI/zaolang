"""One-time, idempotent backfill of a canvas' legacy `graph_json` payload
into the `canvas_nodes` / `canvas_edges` / `canvas_changes` row store.

`a7f2c4d9e310` (`back/alembic/versions/20260903_0900_add_canvas_projects.py`)
introduced the six-table row store. `d4e8b2c6a170`
(`back/alembic/versions/20260909_2230_repair_canvas_row_tables.py`) repaired a
production database that had been stamped past that revision without ever
growing the tables — but deliberately left the old `graph_json`/`revision`
columns in place and did not touch data (see that migration's docstring).

Neither migration backfills a card. A canvas created before the row store
existed still carries its content only in the old JSON `graph_json` column,
which `app.models.canvas.CanvasProject` no longer maps and
`app.domain.canvas.graph_service` never reads — opening one of those canvases
today renders empty even though the schema is now healthy.

This script finds every canvas whose `graph_json` still has nodes but whose
row store is empty, and replays each old node/edge as a
`graph_service.apply_ops` `node.create`/`edge.create` — the exact same
validated path a browser's autosave takes, so a backfilled card gets the same
coordinate/kind/binding checks a live client's card would. Guarded by "row
store is still empty for this canvas" so a second run is a no-op; nothing here
ever reads or writes `graph_json` itself (that column is legacy-read-only by
convention, not a live source of truth to keep in sync).

`graph_json` is not a column every `canvas_projects` table has — a database
that ran `a7f2c4d9e310` in its current (row-store) shape from the start never
grew it, same as `d4e8b2c6a170`'s own "inspect, then add only what is
missing" caution. This script inspects for the column first and is a
guaranteed no-op — not an error — anywhere it is absent.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import session_scope
from app.domain.canvas import graph_service

logger = logging.getLogger(__name__)


def run(*, session: Session | None = None) -> dict[str, int]:
    """Passing `session` is for tests (they own the transaction). Production
    callers omit it and go through `session_scope`."""
    if session is not None:
        return _backfill(session)
    with session_scope() as owned:
        return _backfill(owned)


_EMPTY_RESULT: dict[str, int] = {
    "projects_touched": 0,
    "projects_skipped_nonempty_row_store": 0,
    "nodes_created": 0,
    "edges_created": 0,
}


def _backfill(session: Session) -> dict[str, int]:
    columns = {c["name"] for c in sa_inspect(session.get_bind()).get_columns("canvas_projects")}
    if "graph_json" not in columns:
        # Nothing to do: this database's `canvas_projects` never carried the
        # pre-row-store JSON shape in the first place.
        return dict(_EMPTY_RESULT)

    # Not an ORM-mapped column any more (see `app.models.canvas.CanvasProject`),
    # so it has to be read with a plain SELECT rather than through the model.
    rows = session.execute(
        text("SELECT id, owner_user_id, graph_json FROM canvas_projects WHERE graph_json IS NOT NULL")
    ).all()

    projects_touched: list[str] = []
    projects_skipped_nonempty_row_store = 0
    nodes_created = 0
    edges_created = 0

    for canvas_id, owner_user_id, legacy in rows:
        legacy = legacy or {}
        legacy_nodes = [n for n in (legacy.get("nodes") or []) if isinstance(n, dict)]
        legacy_edges = [e for e in (legacy.get("edges") or []) if isinstance(e, dict)]
        if not legacy_nodes:
            continue
        if graph_service.node_count(session, canvas_id) > 0:
            # Already backfilled by an earlier run of this script, or a
            # canvas that has since been used normally through the live row
            # store — either way the rows already hold the truth.
            projects_skipped_nonempty_row_store += 1
            continue

        ops: list[dict[str, Any]] = [
            {"op_id": f"backfill-node-{i}", "kind": "node.create", "node": node}
            for i, node in enumerate(legacy_nodes)
        ] + [
            {"op_id": f"backfill-edge-{i}", "kind": "edge.create", "edge": edge}
            for i, edge in enumerate(legacy_edges)
        ]

        result = graph_service.apply_ops(
            session,
            canvas_id=canvas_id,
            user_id=owner_user_id,
            ops=ops,
        )
        if result.conflicts:
            # `node.create`/`edge.create` never report a conflict in
            # `graph_service.apply_ops` today — this only fires if that
            # contract changes underneath this script.
            logger.warning(
                "canvas %s backfill reported %d unexpected conflict(s): %s",
                canvas_id,
                len(result.conflicts),
                result.conflicts,
            )

        this_nodes = sum(1 for o in ops if o["kind"] == "node.create")
        this_edges = sum(1 for o in ops if o["kind"] == "edge.create")
        projects_touched.append(canvas_id)
        nodes_created += this_nodes
        edges_created += this_edges
        logger.info(
            "canvas %s: backfilled %d node(s) / %d edge(s) from legacy graph_json",
            canvas_id,
            this_nodes,
            this_edges,
        )

    return {
        "projects_touched": len(projects_touched),
        "projects_skipped_nonempty_row_store": projects_skipped_nonempty_row_store,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    counts = run()
    print(f"画布行表回填完成: {counts}")


if __name__ == "__main__":
    main()
