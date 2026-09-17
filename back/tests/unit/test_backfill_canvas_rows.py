"""`app.scripts.backfill_canvas_rows` — replaying a legacy JSON canvas graph
into the row store idempotently.

`graph_json` is not a column every `canvas_projects` table has (see the
script's own docstring and `d4e8b2c6a170`'s) — these tests add it by hand to
reproduce the one drifted shape the script exists for, rather than assuming
the local schema carries it.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.canvas import graph_service
from app.models import CanvasProject, User
from app.scripts import backfill_canvas_rows


def _add_legacy_graph_json_column(session: Session) -> None:
    session.execute(text("ALTER TABLE canvas_projects ADD COLUMN IF NOT EXISTS graph_json JSONB"))
    session.flush()


def _legacy_canvas(
    session: Session,
    owner: User,
    *,
    nodes: list[dict],
    edges: list[dict] | None = None,
) -> str:
    """A canvas whose only content lives in the pre-row-store `graph_json`
    column — the shape a database stamped past `a7f2c4d9e310` without ever
    running it left behind."""
    project = CanvasProject(
        owner_user_id=owner.id,
        series_id=None,
        title="旧画布",
        viewport_json={},
        change_seq=0,
        updated_by_user_id=owner.id,
    )
    session.add(project)
    session.flush()
    session.execute(
        text("UPDATE canvas_projects SET graph_json = CAST(:graph AS jsonb) WHERE id = :id"),
        {"graph": json.dumps({"nodes": nodes, "edges": edges or []}), "id": project.id},
    )
    session.flush()
    return project.id


def test_backfill_is_a_noop_when_the_database_never_had_the_legacy_column(
    db: Session, author: User
) -> None:
    """The default local/CI schema — `a7f2c4d9e310` as currently written
    never creates `graph_json` at all — must not error just because this
    script exists."""
    result = backfill_canvas_rows.run(session=db)
    assert result == {
        "projects_touched": 0,
        "projects_skipped_nonempty_row_store": 0,
        "nodes_created": 0,
        "edges_created": 0,
    }


def test_backfill_replays_legacy_nodes_and_edges_into_the_row_store(
    db: Session, author: User
) -> None:
    _add_legacy_graph_json_column(db)
    canvas_id = _legacy_canvas(
        db,
        author,
        nodes=[
            {
                "id": "cnd_legacy1",
                "kind": "series",
                "position": {"x": 0, "y": 0},
                "size": {"width": 240, "height": 72},
                "binding": {"kind": "series"},
                "data": {"label": "旧剧集卡"},
            },
            {
                "id": "cnd_legacy2",
                "kind": "episode",
                "position": {"x": 300, "y": 0},
                "data": {"label": "第 1 集"},
            },
        ],
        edges=[{"id": "cne_legacy1", "source": "cnd_legacy1", "target": "cnd_legacy2"}],
    )

    result = backfill_canvas_rows.run(session=db)

    assert result == {
        "projects_touched": 1,
        "projects_skipped_nonempty_row_store": 0,
        "nodes_created": 2,
        "edges_created": 1,
    }
    nodes = {node.id: node for node in graph_service.read_nodes(db, canvas_id)}
    assert set(nodes) == {"cnd_legacy1", "cnd_legacy2"}
    assert nodes["cnd_legacy1"].node_kind == "series"
    assert nodes["cnd_legacy1"].position_x == 0
    assert nodes["cnd_legacy1"].width == 240
    assert nodes["cnd_legacy1"].data_json == {"label": "旧剧集卡"}
    assert nodes["cnd_legacy2"].position_x == 300

    edges = graph_service.read_edges(db, canvas_id)
    assert len(edges) == 1
    assert edges[0].source_node_id == "cnd_legacy1"
    assert edges[0].target_node_id == "cnd_legacy2"

    project = db.get(CanvasProject, canvas_id)
    assert project is not None
    assert project.change_seq == 3  # 2 node creates + 1 edge create


def test_backfill_skips_a_canvas_whose_row_store_already_has_nodes(
    db: Session, author: User
) -> None:
    """A second run — or a canvas that has since been used normally through
    the live row store — must not duplicate cards."""
    _add_legacy_graph_json_column(db)
    canvas_id = _legacy_canvas(
        db,
        author,
        nodes=[{"id": "cnd_legacy1", "kind": "series", "position": {"x": 0, "y": 0}}],
    )

    first = backfill_canvas_rows.run(session=db)
    assert first["projects_touched"] == 1

    second = backfill_canvas_rows.run(session=db)
    assert second == {
        "projects_touched": 0,
        "projects_skipped_nonempty_row_store": 1,
        "nodes_created": 0,
        "edges_created": 0,
    }
    assert graph_service.node_count(db, canvas_id) == 1


def test_backfill_skips_a_canvas_with_no_legacy_nodes(db: Session, author: User) -> None:
    """An empty free canvas (no cards ever placed) has `graph_json = {}` —
    nothing to replay, and it must not be counted as touched."""
    _add_legacy_graph_json_column(db)
    canvas_id = _legacy_canvas(db, author, nodes=[])

    result = backfill_canvas_rows.run(session=db)

    assert result["projects_touched"] == 0
    assert graph_service.node_count(db, canvas_id) == 0
