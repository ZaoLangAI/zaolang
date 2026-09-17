"""Infinite-canvas projects — the two modes, access boundaries, and the
batched hydration read.

The behaviours pinned here are the ones a refactor could plausibly break
without any type error: that a free canvas is strictly personal while a
drama canvas follows the series' *management* grant, and that hydration stays
a fixed number of queries rather than fanning out per node.

The graph write path has its own file — `test_canvas_graph_ops.py`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.domain.editor import collaborators as collab_service
from app.models import (
    Asset,
    CanvasProject,
    CreationSkill,
    DramaEpisode,
    Series,
    SeriesCollaborator,
    User,
)
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    CreationSkillCategory,
    MediaType,
    SeriesCollaboratorStatus,
    SeriesKind,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user


def _set_canvas_flag(session: Session, *, enabled: bool) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": enabled})
    config_service.set_value(session, "feature_flags", value, actor_user_id=None, note="test")


def _make_series(session: Session, owner: User, *, title: str = "测试短剧") -> Series:
    series = Series(
        owner_user_id=owner.id,
        title=title,
        kind=SeriesKind.DRAMA,
        target_platforms_json=["douyin"],
    )
    session.add(series)
    session.flush()
    return series


def _create_ops(node_ids: list[str], edges: list[tuple[str, str]] | None = None) -> list[dict]:
    """Operations that build the given cards and connections from nothing."""
    ops: list[dict] = [
        {
            "op_id": f"op_n{i}",
            "kind": "node.create",
            "node": {"id": nid, "kind": "note", "position": {"x": i * 100, "y": 0}, "data": {}},
        }
        for i, nid in enumerate(node_ids)
    ]
    ops += [
        {
            "op_id": f"op_e{i}",
            "kind": "edge.create",
            "edge": {"id": f"cne_{i}", "source": src, "target": dst},
        }
        for i, (src, dst) in enumerate(edges or [])
    ]
    return ops


def _apply(client: TestClient, user: User, canvas_id: str, ops: list[dict], *, base_seq: int = 0):
    return client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={"base_seq": base_seq, "ops": ops},
        headers=auth_header(user),
    )


def _image_node(node_id: str, asset_id: str) -> dict:
    return {
        "op_id": "op_img",
        "kind": "node.create",
        "node": {
            "id": node_id,
            "kind": "image",
            "position": {"x": 0, "y": 0},
            "binding": {"kind": "image", "asset_id": asset_id},
        },
    }


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------


def test_canvas_routes_404_while_the_flag_is_off(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=False)
    response = client.get("/v1/canvas-projects", headers=auth_header(author))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# The two modes
# ---------------------------------------------------------------------------


def test_free_canvas_needs_no_series_and_reports_free_mode(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    response = client.post(
        "/v1/canvas-projects", json={"title": "灵感沙盒"}, headers=auth_header(author)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "free"
    assert body["series_id"] is None
    # A fresh canvas has had no writes, so its cursor sits at the origin.
    assert body["change_seq"] == 0
    assert body["nodes"] == []
    assert body["edges"] == []
    # Nothing to hydrate without a series.
    assert body["snapshot"]["episodes"] == []
    assert body["snapshot"]["series"] is None


def test_series_canvas_is_resolve_or_create_and_reuses_the_same_row(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)

    first = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author))
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "drama"
    # Title defaults to the series' own, so the button needs no naming step.
    assert first.json()["title"] == series.title

    second = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author))
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    assert db.scalar(select(func.count()).select_from(CanvasProject)) == 1


def test_a_series_cannot_have_two_canvases(client: TestClient, db: Session, author: User) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author))

    duplicate = client.post(
        "/v1/canvas-projects",
        json={"title": "第二个画布", "series_id": series.id},
        headers=auth_header(author),
    )
    assert duplicate.status_code == 422
    assert db.scalar(select(func.count()).select_from(CanvasProject)) == 1


# ---------------------------------------------------------------------------
# Compare-and-set writes
# ---------------------------------------------------------------------------


def test_the_project_patch_carries_metadata_only(
    client: TestClient, db: Session, author: User
) -> None:
    """Title and viewport are all a PATCH may touch.

    The graph moved to its own route because a document-shaped write gives the
    browser and a worker landing a generated card one cell to fight over.
    """
    _set_canvas_flag(db, enabled=True)
    created = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()

    response = client.patch(
        f"/v1/canvas-projects/{created['id']}",
        json={"title": "改名了", "viewport": {"x": 12, "y": -4, "zoom": 0.75}},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "改名了"
    assert body["viewport"] == {"x": 12, "y": -4, "zoom": 0.75}
    # Bumped so a client listening on the feed learns to re-read the row.
    assert body["change_seq"] > created["change_seq"]


def test_a_graph_write_does_not_resend_the_domain_snapshot(
    client: TestClient, db: Session, author: User
) -> None:
    """A graph write cannot change the hydration — and re-sending it made most
    of every autosave response redundant, growing with each episode's script."""
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    db.add(
        DramaEpisode(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="第一集",
            script_json={"title": "x" * 2000, "scenes": [], "characters": []},
        )
    )
    db.flush()
    canvas = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()
    assert canvas["snapshot"]["episodes"], "GET must still hydrate"

    written = _apply(
        client,
        author,
        canvas["id"],
        _create_ops(["cnd_a"]),
        base_seq=canvas["change_seq"],
    )
    assert written.status_code == 200, written.text
    body = written.json()
    assert "snapshot" not in body
    # What the client does need: its new cursor, and confirmation the op landed.
    assert body["applied"] == ["op_n0"]
    assert body["conflicts"] == []
    assert body["change_seq"] > canvas["change_seq"]


def test_referenced_character_and_scene_cards_are_hydrated(
    client: TestClient, db: Session, author: User
) -> None:
    """Skill nodes read from what episodes actually reference. This used to
    key off `Series.character_ids_json`, which is dead in this codebase —
    every writer sets `[]` — so the list was permanently empty."""
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    skill = CreationSkill(
        owner_user_id=author.id,
        title="女主角",
        category=CreationSkillCategory.CHARACTER,
    )
    db.add(skill)
    db.flush()
    db.add(
        DramaEpisode(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="第一集",
            source_referenced_skill_ids_json=[skill.id],
            script_json={"title": "t", "scenes": [], "characters": []},
        )
    )
    db.flush()

    snapshot = client.get(
        f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)
    ).json()["snapshot"]
    assert [s["title"] for s in snapshot["skills"]] == ["女主角"]


def test_a_skill_referenced_only_from_the_script_document_is_hydrated(
    client: TestClient, db: Session, author: User
) -> None:
    """The other live source: a character chip linked from inside the script."""
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    skill = CreationSkill(
        owner_user_id=author.id, title="反派", category=CreationSkillCategory.CHARACTER
    )
    db.add(skill)
    db.flush()
    db.add(
        DramaEpisode(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="第一集",
            script_json={
                "title": "t",
                "characters": [{"name": "反派", "traits": "", "character_ref_id": skill.id}],
                "scenes": [],
            },
        )
    )
    db.flush()

    snapshot = client.get(
        f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)
    ).json()["snapshot"]
    assert [s["id"] for s in snapshot["skills"]] == [skill.id]


def _make_asset(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=16,
        checksum_sha256="0" * 64,
        role=AssetRole.GENERATION_REFERENCE,
        width=8,
        height=8,
    )
    session.add(asset)
    session.flush()
    return asset


def test_a_picture_node_gets_its_asset_url_resolved(
    client: TestClient, db: Session, author: User
) -> None:
    """A card stores only an asset id — a presigned URL would expire, so the
    canvas would render for an hour and then show broken images forever."""
    _set_canvas_flag(db, enabled=True)
    asset = _make_asset(db, author)
    created = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()
    applied = _apply(client, author, created["id"], [_image_node("cnd_i", asset.id)])
    assert applied.status_code == 200, applied.text

    body = client.get(f"/v1/canvas-projects/{created['id']}", headers=auth_header(author)).json()
    resolved = body["snapshot"]["assets"][asset.id]
    assert resolved["url"]
    assert resolved["media_type"] == MediaType.IMAGE
    assert (resolved["width"], resolved["height"]) == (8, 8)


def test_a_foreign_asset_id_pasted_into_the_graph_is_not_resolved(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """Card rows are client-written, so an id put there must never become a
    read primitive for someone else's private object."""
    _set_canvas_flag(db, enabled=True)
    someone_elses = _make_asset(db, remixer)
    created = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()
    applied = _apply(client, author, created["id"], [_image_node("cnd_i", someone_elses.id)])
    # The card itself is fine to hold — it is the *resolution* that is gated.
    assert applied.status_code == 200, applied.text

    body = client.get(f"/v1/canvas-projects/{created['id']}", headers=auth_header(author)).json()
    assert [node["id"] for node in body["nodes"]] == ["cnd_i"]
    # Silently omitted, which the client renders as a stale card.
    assert body["snapshot"]["assets"] == {}


def test_an_edge_pointing_at_a_missing_node_is_rejected(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    created = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()

    ops = _create_ops(["cnd_a"])
    ops.append(
        {
            "op_id": "op_ghost",
            "kind": "edge.create",
            "edge": {"id": "cne_x", "source": "cnd_a", "target": "cnd_ghost"},
        }
    )
    response = _apply(client, author, created["id"], ops)
    assert response.status_code == 422


def test_duplicate_node_ids_are_rejected(client: TestClient, db: Session, author: User) -> None:
    """Named 422 rather than the primary key's IntegrityError, which would
    surface as a 500 and take the rest of the batch with it."""
    _set_canvas_flag(db, enabled=True)
    created = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()

    response = _apply(client, author, created["id"], _create_ops(["cnd_a", "cnd_a"]))
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Access boundaries
# ---------------------------------------------------------------------------


def test_a_free_canvas_is_invisible_to_everyone_but_its_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    created = client.post(
        "/v1/canvas-projects", json={"title": "私人沙盒"}, headers=auth_header(author)
    ).json()

    outsider = client.get(f"/v1/canvas-projects/{created['id']}", headers=auth_header(remixer))
    # 404, not 403 — its existence is not confirmed.
    assert outsider.status_code == 404
    assert client.get("/v1/canvas-projects", headers=auth_header(remixer)).json() == []


def test_an_active_collaborator_can_read_and_arrange_the_series_canvas(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    membership = SeriesCollaborator(
        series_id=series.id,
        user_id=remixer.id,
        invited_by_user_id=author.id,
        status=SeriesCollaboratorStatus.ACTIVE,
    )
    db.add(membership)
    db.flush()
    canvas = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()

    detail = client.get(f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(remixer))
    assert detail.status_code == 200
    # The UI mirrors the server boundary off this field.
    assert detail.json()["viewer_role"] == "collaborator"

    arranged = _apply(
        client, remixer, canvas["id"], _create_ops(["cnd_x"]), base_seq=canvas["change_seq"]
    )
    assert arranged.status_code == 200
    assert arranged.json()["applied"] == ["op_n0"]

    listed = client.get("/v1/canvas-projects", headers=auth_header(remixer)).json()
    assert [row["id"] for row in listed] == [canvas["id"]]

    collab_service.remove(
        db, actor_user_id=remixer.id, series_id=series.id, collaborator_id=membership.id
    )
    db.flush()
    assert client.get("/v1/canvas-projects", headers=auth_header(remixer)).json() == []
    assert (
        client.get(f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(remixer)).status_code
        == 404
    )


def test_a_pending_invite_is_not_yet_access(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    db.add(
        SeriesCollaborator(
            series_id=series.id,
            user_id=remixer.id,
            invited_by_user_id=author.id,
            status=SeriesCollaboratorStatus.PENDING,
        )
    )
    db.flush()
    canvas = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()

    assert (
        client.get(f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(remixer)).status_code
        == 404
    )


def test_deleting_the_canvas_stays_owner_only_even_for_a_collaborator(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """Deleting the workspace is not part of the management grant — same
    boundary trash/purge already draw."""
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    db.add(
        SeriesCollaborator(
            series_id=series.id,
            user_id=remixer.id,
            invited_by_user_id=author.id,
            status=SeriesCollaboratorStatus.ACTIVE,
        )
    )
    db.flush()
    canvas = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()

    refused = client.delete(f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(remixer))
    assert refused.status_code == 404
    assert db.get(CanvasProject, canvas["id"]) is not None

    allowed = client.delete(f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(author))
    assert allowed.status_code == 204


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------


def test_hydration_returns_episodes_and_scripts_in_one_request(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    for number in (1, 2):
        db.add(
            DramaEpisode(
                series_id=series.id,
                season_number=1,
                episode_number=number,
                title=f"第 {number} 集",
                script_json={"title": f"第 {number} 集", "scenes": [], "characters": []},
            )
        )
    db.flush()

    body = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()
    snapshot = body["snapshot"]
    assert snapshot["series"]["title"] == series.title
    assert [e["episode_number"] for e in snapshot["episodes"]] == [1, 2]
    # The script document rides along, so the client can derive breakpoints
    # with the same helper the script studio uses.
    assert snapshot["episodes"][0]["script"]["title"] == "第 1 集"


def test_hydration_query_count_does_not_grow_with_episode_count(
    client: TestClient, db: Session, author: User
) -> None:
    """The whole reason the batched endpoint exists. If this starts scaling
    with N, someone reintroduced a per-row fan-out."""
    _set_canvas_flag(db, enabled=True)

    def query_count_for(episode_count: int) -> int:
        series = _make_series(db, author, title=f"短剧-{episode_count}")
        for number in range(1, episode_count + 1):
            db.add(
                DramaEpisode(
                    series_id=series.id,
                    season_number=1,
                    episode_number=number,
                    title=f"第 {number} 集",
                    script_json={"title": "x", "scenes": [], "characters": []},
                )
            )
        db.flush()
        canvas = client.get(
            f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)
        ).json()

        counter = {"n": 0}

        def _count(*_args: object, **_kwargs: object) -> None:
            counter["n"] += 1

        event.listen(db.get_bind(), "before_cursor_execute", _count)
        try:
            response = client.get(
                f"/v1/canvas-projects/{canvas['id']}", headers=auth_header(author)
            )
            assert response.status_code == 200
            assert len(response.json()["snapshot"]["episodes"]) == episode_count
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _count)
        return counter["n"]

    small = query_count_for(2)
    large = query_count_for(12)
    # Ten more episodes must not cost ten more queries. A small constant
    # allowance covers auth/config reads, not per-episode work.
    assert large <= small + 2, f"hydration fanned out: {small} -> {large} queries"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_deleting_a_series_takes_its_canvas_but_leaves_free_canvases(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    series = _make_series(db, author)
    bound = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(author)).json()
    free = client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(author)
    ).json()

    db.delete(db.get(Series, series.id))
    db.flush()

    assert db.get(CanvasProject, bound["id"]) is None
    assert db.get(CanvasProject, free["id"]) is not None


def test_an_outsider_cannot_open_a_canvas_for_someone_elses_series(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    stranger = make_user(db, email="stranger@example.com", handle="stranger")
    series = _make_series(db, author)

    response = client.get(f"/v1/drama-series/{series.id}/canvas", headers=auth_header(stranger))
    assert response.status_code == 404
    assert db.scalar(select(func.count()).select_from(CanvasProject)) == 0
