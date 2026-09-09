"""Races on one canvas.

This file is the acceptance criterion for the whole canvas persistence design.

The feature exists to let an Agent generate onto the canvas, which means a
Celery worker inserts a card whenever a generation happens to finish — possibly
minutes later, and certainly while someone is dragging things around. The
previous shape stored the graph as one `graph_json` document guarded by a
canvas-wide `revision`, so both writers issued `UPDATE canvas_projects SET
graph_json = ?`: the document *was* the granule, and one of the two always lost.

If the test below passes, the rewrite has delivered its one job.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.canvas import graph_service
from app.models import CanvasChange, CanvasNode, CanvasProject, User
from app.models.enums import CanvasNodeKind, CanvasNodeOrigin
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user

SessionFactory = Callable[[], Session]


def _seed_canvas(session: Session) -> tuple[User, CanvasProject]:
    user = make_user(session, email="canvas-racer@example.com", handle="canvasracer")
    project = CanvasProject(
        owner_user_id=user.id,
        series_id=None,
        title="竞态画布",
        viewport_json={},
        change_seq=0,
        updated_by_user_id=user.id,
    )
    session.add(project)
    session.flush()
    return user, project


def _create_op(op_id: str, node_id: str, x: int) -> dict:
    return {
        "op_id": op_id,
        "kind": "node.create",
        "node": {"id": node_id, "kind": "note", "position": {"x": x, "y": 0}, "data": {}},
    }


def test_a_client_batch_and_an_agent_landing_do_not_lose_each_other(
    sessions: SessionFactory,
) -> None:
    """The whole point of the rewrite, in one test.

    A browser flushes a batch of layout operations at the same instant a worker
    lands a generated card. Both must commit. Under the old whole-document CAS
    exactly one of these could survive, because both wrote the same cell.
    """
    setup = sessions()
    user, project = _seed_canvas(setup)
    canvas_id = project.id
    setup.commit()

    def client_batch(session: Session) -> graph_service.ApplyResult:
        return graph_service.apply_ops(
            session,
            canvas_id=canvas_id,
            user_id=user.id,
            ops=[_create_op("op_a", "cnd_client_a", 0), _create_op("op_b", "cnd_client_b", 200)],
        )

    def agent_landing(session: Session) -> str:
        node, _ = graph_service.insert_agent_node(
            session,
            canvas_id=canvas_id,
            node_kind=CanvasNodeKind.IMAGE,
            position=(400, 0),
            binding={"kind": "image", "asset_id": "ast_generated"},
            actor_user_id=user.id,
        )
        return node.id

    outcomes = run_in_parallel(
        [
            race(client_batch, sessions),
            race(agent_landing, sessions),
        ]
    )
    for outcome in outcomes:
        assert not isinstance(outcome, BaseException), f"a writer lost: {outcome!r}"

    check = sessions()
    stored = list(check.scalars(select(CanvasNode).where(CanvasNode.canvas_id == canvas_id)))
    ids = {node.id for node in stored}
    assert "cnd_client_a" in ids, "the browser's cards were lost"
    assert "cnd_client_b" in ids
    agent_nodes = [node for node in stored if node.origin == CanvasNodeOrigin.AGENT]
    assert len(agent_nodes) == 1, "the generated card was lost"
    assert agent_nodes[0].binding_asset_id == "ast_generated"


def test_the_sequence_orders_concurrent_writers_without_rejecting_one(
    sessions: SessionFactory,
) -> None:
    """`change_seq` replaced a compare-and-set token with a lock.

    The distinction is the design: the old `revision` made two writers contend
    for one number and rejected the loser; this makes them queue for a few
    microseconds and hands each a disjoint range. Every write gets a unique,
    monotonic sequence, and nobody is turned away.
    """
    setup = sessions()
    user, project = _seed_canvas(setup)
    canvas_id = project.id
    setup.commit()

    writers = 6

    def writer(index: int) -> Callable[[Session], graph_service.ApplyResult]:
        def work(session: Session) -> graph_service.ApplyResult:
            return graph_service.apply_ops(
                session,
                canvas_id=canvas_id,
                user_id=user.id,
                ops=[_create_op(f"op_{index}", f"cnd_{index}", index * 100)],
            )

        return work

    outcomes = run_in_parallel([race(writer(i), sessions) for i in range(writers)])
    for outcome in outcomes:
        assert not isinstance(outcome, BaseException), f"a writer was rejected: {outcome!r}"

    check = sessions()
    seqs = list(
        check.scalars(
            select(CanvasChange.seq)
            .where(CanvasChange.canvas_id == canvas_id)
            .order_by(CanvasChange.seq)
        )
    )
    assert len(seqs) == writers, "every writer must appear in the feed"
    # Unique and ordered — which is what makes it usable as a resume cursor.
    assert len(set(seqs)) == len(seqs)
    assert seqs == sorted(seqs)

    nodes = list(check.scalars(select(CanvasNode.id).where(CanvasNode.canvas_id == canvas_id)))
    assert len(nodes) == writers


def test_two_windows_moving_the_same_card_leaves_exactly_one_winner(
    sessions: SessionFactory,
) -> None:
    """Per-card compare-and-set still has to be real.

    Making writes coexist must not mean making them silently overwrite: two
    windows dragging the *same* card is a genuine conflict, and exactly one of
    them may land.
    """
    setup = sessions()
    user, project = _seed_canvas(setup)
    canvas_id = project.id
    graph_service.apply_ops(
        setup,
        canvas_id=canvas_id,
        user_id=user.id,
        ops=[_create_op("op_seed", "cnd_shared", 0)],
    )
    setup.commit()

    def mover(x: int) -> Callable[[Session], graph_service.ApplyResult]:
        def work(session: Session) -> graph_service.ApplyResult:
            return graph_service.apply_ops(
                session,
                canvas_id=canvas_id,
                user_id=user.id,
                ops=[
                    {
                        "op_id": f"op_move_{x}",
                        "kind": "node.update",
                        "node_id": "cnd_shared",
                        # Both quote revision 1 — neither saw the other.
                        "expected_revision": 1,
                        "position": {"x": x, "y": 0},
                    }
                ],
            )

        return work

    outcomes = run_in_parallel([race(mover(111), sessions), race(mover(222), sessions)])
    results = [o for o in outcomes if isinstance(o, graph_service.ApplyResult)]
    # Neither request fails — a conflict is reported, not raised.
    assert len(results) == 2, f"a mover errored instead of conflicting: {outcomes!r}"

    applied = sum(len(result.applied) for result in results)
    conflicted = sum(len(result.conflicts) for result in results)
    assert (applied, conflicted) == (1, 1), "exactly one move may win"

    check = sessions()
    node = check.get(CanvasNode, "cnd_shared")
    assert node is not None
    assert node.position_x in (111, 222)
    assert node.revision == 2
