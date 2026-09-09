"""The canvas graph write path.

Everything here exists because of one requirement: a worker landing a generated
card and a browser autosaving a drag must both succeed. The old shape — one
`graph_json` document guarded by a whole-canvas `revision` — could not do that,
because the document *was* the granule and one of the two writers always lost.

So the behaviours pinned here are the ones that replaced it: compare-and-set is
per card, a stale op costs you that card and nothing else, and the change feed
reports deletes (which a vanished row cannot report for itself).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


def _set_canvas_flag(session: Session, *, enabled: bool) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": enabled})
    config_service.set_value(session, "feature_flags", value, actor_user_id=None, note="test")


def _canvas(client: TestClient, user: User, title: str = "沙盒") -> dict:
    return client.post(
        "/v1/canvas-projects", json={"title": title}, headers=auth_header(user)
    ).json()


def _apply(client: TestClient, user: User, canvas_id: str, ops: list[dict], *, base_seq: int = 0):
    return client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={"base_seq": base_seq, "ops": ops},
        headers=auth_header(user),
    )


def _note(op_id: str, node_id: str, *, x: int = 0, y: int = 0) -> dict:
    return {
        "op_id": op_id,
        "kind": "node.create",
        "node": {"id": node_id, "kind": "note", "position": {"x": x, "y": y}, "data": {}},
    }


def _read(client: TestClient, user: User, canvas_id: str) -> dict:
    return client.get(f"/v1/canvas-projects/{canvas_id}", headers=auth_header(user)).json()


def _node_by_id(body: dict, node_id: str) -> dict | None:
    return next((node for node in body["nodes"] if node["id"] == node_id), None)


# ---------------------------------------------------------------------------
# Applying operations
# ---------------------------------------------------------------------------


def test_creates_land_and_report_their_own_revision(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)

    response = _apply(client, author, canvas["id"], [_note("op_a", "cnd_a", x=40, y=10)])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == ["op_a"]
    assert body["conflicts"] == []

    stored = _node_by_id(_read(client, author, canvas["id"]), "cnd_a")
    assert stored is not None
    assert stored["position"] == {"x": 40, "y": 10}
    # A brand-new card starts at 1; this is the token the next update quotes.
    assert stored["revision"] == 1
    assert stored["origin"] == "user"


def test_an_update_only_touches_the_fields_it_sends(
    client: TestClient, db: Session, author: User
) -> None:
    """A drag sends a position, not a whole card.

    Treating an omitted field as "clear it" would make every drag wipe the
    card's text, which is the sort of loss no undo stack can explain.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_a",
                "kind": "node.create",
                "node": {
                    "id": "cnd_a",
                    "kind": "note",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "别丢了我"},
                },
            }
        ],
    )

    moved = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_move",
                "kind": "node.update",
                "node_id": "cnd_a",
                "expected_revision": 1,
                "position": {"x": 300, "y": 120},
            }
        ],
    )
    assert moved.status_code == 200, moved.text

    stored = _node_by_id(_read(client, author, canvas["id"]), "cnd_a")
    assert stored is not None
    assert stored["position"] == {"x": 300, "y": 120}
    assert stored["data"]["label"] == "别丢了我"
    assert stored["revision"] == 2


def test_a_stale_op_conflicts_alone_while_the_rest_of_the_batch_lands(
    client: TestClient, db: Session, author: User
) -> None:
    """The single most important behaviour in this feature.

    The old whole-document CAS answered a stale write with a 409 and threw the
    entire batch away. Here the stale op is reported and skipped, and every
    other edit in the same flush still commits — losing twenty accepted drags
    because a twenty-first card moved under one of them protects nothing.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a"), _note("op_b", "cnd_b")])

    # Another window moves cnd_a, taking it to revision 2.
    _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_other",
                "kind": "node.update",
                "node_id": "cnd_a",
                "expected_revision": 1,
                "position": {"x": 999, "y": 999},
            }
        ],
    )

    # This window still believes cnd_a is at revision 1, and also moves cnd_b.
    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_stale",
                "kind": "node.update",
                "node_id": "cnd_a",
                "expected_revision": 1,
                "position": {"x": 5, "y": 5},
            },
            {
                "op_id": "op_good",
                "kind": "node.update",
                "node_id": "cnd_b",
                "expected_revision": 1,
                "position": {"x": 77, "y": 77},
            },
        ],
    )
    # Not a 409: a partial outcome is the honest one, and the client can act
    # on it.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == ["op_good"]
    assert [c["op_id"] for c in body["conflicts"]] == ["op_stale"]
    assert body["conflicts"][0]["reason"] == "stale_revision"

    current = _read(client, author, canvas["id"])
    a = _node_by_id(current, "cnd_a")
    b = _node_by_id(current, "cnd_b")
    assert a is not None and b is not None
    # The winner's move survived; the stale one never happened.
    assert a["position"] == {"x": 999, "y": 999}
    # The unrelated edit in the losing batch still landed.
    assert b["position"] == {"x": 77, "y": 77}


def test_an_update_to_a_deleted_card_reports_missing_rather_than_stale(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])
    _apply(
        client,
        author,
        canvas["id"],
        [{"op_id": "op_del", "kind": "node.delete", "node_id": "cnd_a", "expected_revision": 1}],
    )

    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_ghost",
                "kind": "node.update",
                "node_id": "cnd_a",
                "expected_revision": 1,
                "position": {"x": 1, "y": 1},
            }
        ],
    )
    assert response.status_code == 200
    conflicts = response.json()["conflicts"]
    # The distinction matters to the client: "stale" means re-read and retry,
    # "missing" means drop the card from the local graph.
    assert conflicts[0]["reason"] == "missing"


def test_creating_the_same_edge_twice_is_success_not_a_conflict(
    client: TestClient, db: Session, author: User
) -> None:
    """A retried flush must not fail. Edges have no mutable payload, so the
    endpoint uniqueness constraint makes creation idempotent for free."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a"), _note("op_b", "cnd_b")])

    edge = {
        "op_id": "op_e",
        "kind": "edge.create",
        "edge": {"id": "cne_1", "source": "cnd_a", "target": "cnd_b"},
    }
    first = _apply(client, author, canvas["id"], [edge])
    second = _apply(client, author, canvas["id"], [dict(edge, op_id="op_e2")])
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["applied"] == ["op_e2"]
    assert second.json()["conflicts"] == []

    assert len(_read(client, author, canvas["id"])["edges"]) == 1


def test_deleting_an_already_deleted_edge_is_success(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    response = _apply(
        client,
        author,
        canvas["id"],
        [{"op_id": "op_d", "kind": "edge.delete", "edge_id": "cne_never_existed"}],
    )
    # The world already looks the way the client asked for.
    assert response.status_code == 200
    assert response.json()["applied"] == ["op_d"]


def test_an_edge_cannot_join_a_card_to_itself(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])
    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_loop",
                "kind": "edge.create",
                "edge": {"id": "cne_l", "source": "cnd_a", "target": "cnd_a"},
            }
        ],
    )
    assert response.status_code == 422


def test_an_unknown_node_kind_is_refused(client: TestClient, db: Session, author: User) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_x",
                "kind": "node.create",
                "node": {"id": "cnd_x", "kind": "wormhole", "position": {"x": 0, "y": 0}},
            }
        ],
    )
    assert response.status_code == 422


def test_a_non_finite_coordinate_is_refused(client: TestClient, db: Session, author: User) -> None:
    """Positions are stored as integers; an out-of-range coordinate would
    otherwise overflow the column and take the whole canvas down on read."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_x",
                "kind": "node.create",
                "node": {"id": "cnd_x", "kind": "note", "position": {"x": 10**12, "y": 0}},
            }
        ],
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The change feed
# ---------------------------------------------------------------------------


def test_deleting_a_card_also_reports_the_edges_that_went_with_it(
    client: TestClient, db: Session, author: User
) -> None:
    """The database cascades those edge rows, but it will not write their
    change entries — and a client catching up by `since` would keep drawing
    lines into a card that is gone."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a"), _note("op_b", "cnd_b")])
    _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_e",
                "kind": "edge.create",
                "edge": {"id": "cne_1", "source": "cnd_a", "target": "cnd_b"},
            }
        ],
    )
    before = _read(client, author, canvas["id"])["change_seq"]

    _apply(
        client,
        author,
        canvas["id"],
        [{"op_id": "op_del", "kind": "node.delete", "node_id": "cnd_a", "expected_revision": 1}],
    )

    feed = client.get(
        f"/v1/canvas-projects/{canvas['id']}/changes?since={before}", headers=auth_header(author)
    ).json()
    assert feed["gap"] is False
    deleted = {
        (c["entity_type"], c["entity_id"]) for c in feed["changes"] if c["action"] == "deleted"
    }
    assert ("node", "cnd_a") in deleted
    assert ("edge", "cne_1") in deleted, "the cascaded edge must be reported too"


def test_deleting_a_well_connected_card_logs_every_edge(
    client: TestClient, db: Session, author: User
) -> None:
    """A hub card takes many edges with it, and each needs its own sequence
    number and change row.

    An earlier cut reserved a fixed block of numbers per batch and walked a
    cursor through it. One delete of a card with more edges than the block
    allowed for would run past the end and start issuing numbers a concurrent
    writer already held — a unique-constraint failure at best, two writers'
    orderings silently interleaved at worst. Numbers are allocated per change
    now, so there is no block to overrun.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    spokes = 8
    _apply(
        client,
        author,
        canvas["id"],
        [_note("op_hub", "cnd_hub")] + [_note(f"op_s{i}", f"cnd_s{i}") for i in range(spokes)],
    )
    _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": f"op_e{i}",
                "kind": "edge.create",
                "edge": {"id": f"cne_{i}", "source": "cnd_hub", "target": f"cnd_s{i}"},
            }
            for i in range(spokes)
        ],
    )
    before = _read(client, author, canvas["id"])["change_seq"]

    response = _apply(
        client,
        author,
        canvas["id"],
        [{"op_id": "op_del", "kind": "node.delete", "node_id": "cnd_hub", "expected_revision": 1}],
        base_seq=before,
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied"] == ["op_del"]

    feed = client.get(
        f"/v1/canvas-projects/{canvas['id']}/changes?since={before}", headers=auth_header(author)
    ).json()
    deleted_edges = {
        c["entity_id"]
        for c in feed["changes"]
        if c["entity_type"] == "edge" and c["action"] == "deleted"
    }
    assert deleted_edges == {f"cne_{i}" for i in range(spokes)}
    # Every change still got a distinct, ordered number.
    seqs = [c["seq"] for c in feed["changes"]]
    assert len(set(seqs)) == len(seqs)
    assert seqs == sorted(seqs)

    remaining = _read(client, author, canvas["id"])
    assert _node_by_id(remaining, "cnd_hub") is None
    assert remaining["edges"] == []


def test_the_write_response_carries_everything_the_client_missed(
    client: TestClient, db: Session, author: User
) -> None:
    """One round trip both writes and catches the client up, so a window that
    fell behind converges without a second request."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    # Another window adds a card this one never saw.
    _apply(client, author, canvas["id"], [_note("op_other", "cnd_other")])

    response = _apply(client, author, canvas["id"], [_note("op_mine", "cnd_mine")], base_seq=0)
    assert response.status_code == 200
    reported = {c["entity_id"] for c in response.json()["changes"]}
    assert {"cnd_other", "cnd_mine"} <= reported


def test_a_batch_of_pure_conflicts_is_not_reported_as_a_gap(
    client: TestClient, db: Session, author: User
) -> None:
    """`changes` being empty is ambiguous on its own.

    It is what an unreconstructable cursor looks like, and also what a batch in
    which every op conflicted looks like. Sequence numbers cannot separate them
    either — they are monotonic but deliberately not dense, since `_next_seq`
    over-reserves per batch. So the server says which one it is, and a client
    that guessed would throw away the conflicts by reloading over them.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a")])
    current = _read(client, author, canvas["id"])["change_seq"]

    response = _apply(
        client,
        author,
        canvas["id"],
        [
            {
                "op_id": "op_stale",
                "kind": "node.update",
                "node_id": "cnd_a",
                "expected_revision": 99,
                "position": {"x": 1, "y": 1},
            }
        ],
        base_seq=current,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["changes"] == []
    assert len(body["conflicts"]) == 1
    # The distinction this test exists for.
    assert body["gap"] is False
    # And the sequence did move, which is why a numeric heuristic would misfire.
    assert body["change_seq"] > current


def test_a_changes_read_from_the_origin_replays_the_whole_history(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    _apply(client, author, canvas["id"], [_note("op_a", "cnd_a"), _note("op_b", "cnd_b")])

    feed = client.get(
        f"/v1/canvas-projects/{canvas['id']}/changes?since=0", headers=auth_header(author)
    ).json()
    assert feed["gap"] is False
    created = [c["entity_id"] for c in feed["changes"] if c["action"] == "created"]
    assert created == ["cnd_a", "cnd_b"]
    # Monotonic, so it is usable as a resume cursor.
    seqs = [c["seq"] for c in feed["changes"]]
    assert seqs == sorted(seqs)


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def test_a_batch_larger_than_the_cap_is_refused(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, author)
    ops = [_note(f"op_{i}", f"cnd_{i}") for i in range(201)]
    response = _apply(client, author, canvas["id"], ops)
    assert response.status_code == 422
