"""The canvas Agent: context, guardrails, pricing and confirmation.

The Agent is the reason the canvas persistence was rewritten, and it is the one
part of this feature that spends the user's money. So the tests that matter are
not "does it plan" — the fake gateway makes that trivially true — but the
refusals: that a hallucinated reference never reaches `submit`, that a plan
cannot raise the quality tier the user chose, that nothing is charged before an
explicit confirm, and that a double-tapped confirm reserves credits once.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.canvas import agent_service
from app.domain.credits import service as credits_service
from app.models import CanvasAgentTask, GenerationJob, User
from app.models.base import new_id
from app.models.enums import (
    CanvasAgentRunStatus,
    CanvasAgentTaskStatus,
    QualityTier,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


def _set_canvas_flag(session: Session, *, enabled: bool) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": enabled})
    config_service.set_value(session, "feature_flags", value, actor_user_id=None, note="test")


def _canvas(client: TestClient, user: User) -> dict:
    return client.post(
        "/v1/canvas-projects", json={"title": "沙盒"}, headers=auth_header(user)
    ).json()


def _apply(client: TestClient, user: User, canvas_id: str, ops: list[dict]) -> dict:
    return client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={"base_seq": 0, "ops": ops},
        headers=auth_header(user),
    ).json()


def _agent_card(node_id: str = "cnd_agent", *, x: int = 100, y: int = 50) -> dict:
    return {
        "op_id": "op_agent",
        "kind": "node.create",
        "node": {
            "id": node_id,
            "kind": "agent",
            "position": {"x": x, "y": y},
            "data": {"label": "助手"},
        },
    }


def _image_card(node_id: str, asset_id: str) -> dict:
    return {
        "op_id": f"op_{node_id}",
        "kind": "node.create",
        "node": {
            "id": node_id,
            "kind": "image",
            "position": {"x": 0, "y": 0},
            "binding": {"kind": "image", "asset_id": asset_id},
        },
    }


def _plan(
    client: TestClient, user: User, canvas_id: str, *, node_id: str = "cnd_agent", **overrides
) -> dict:
    """Runs a planning turn and returns the `complete` payload.

    The route answers with SSE; the run itself is what the assertions are about,
    so the envelope is unwrapped here rather than in every test.
    """
    body = {"agent_node_id": node_id, "goal": "画一张雨夜街头的开场镜头", **overrides}
    response = client.post(
        f"/v1/canvas-projects/{canvas_id}/agent-runs", json=body, headers=auth_header(user)
    )
    assert response.status_code == 202, response.text
    for block in response.text.split("\n\n"):
        lines = block.splitlines()
        if any(line == "event: complete" for line in lines):
            data = next(line[6:] for line in lines if line.startswith("data: "))
            return json.loads(data)
    raise AssertionError(f"no complete frame in stream: {response.text[:500]}")


@pytest.fixture(autouse=True)
def _stream_session(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    """Runs the planner's `_finish` on the test's own transaction.

    The route deliberately opens a fresh `session_scope()` so the resolving
    session can close before the LLM stream finishes. That is right in
    production and impossible in a test: the fixtures roll back rather than
    commit, so a second connection cannot see the user the test just made.
    Same substitution `test_editor_plans_and_races.py` makes for the editor
    planner, which has the identical shape.
    """

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr("app.db.session_scope", fake_session_scope)


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 100_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def test_the_planner_sees_the_selected_card_and_what_feeds_it(
    client: TestClient, db: Session, funded: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(
        client,
        funded,
        canvas["id"],
        [
            _agent_card(),
            {
                "op_id": "op_note",
                "kind": "node.create",
                "node": {
                    "id": "cnd_note",
                    "kind": "note",
                    "position": {"x": 0, "y": 0},
                    "data": {"text": "霓虹灯下的街角"},
                },
            },
            {
                "op_id": "op_far",
                "kind": "node.create",
                "node": {
                    "id": "cnd_unrelated",
                    "kind": "note",
                    "position": {"x": 900, "y": 900},
                    "data": {"text": "无关卡片"},
                },
            },
        ],
    )
    _apply(
        client,
        funded,
        canvas["id"],
        [
            {
                "op_id": "op_edge",
                "kind": "edge.create",
                "edge": {"id": "cne_1", "source": "cnd_note", "target": "cnd_agent"},
            }
        ],
    )

    node_ids, digest = agent_service.upstream_context(
        db, canvas_id=canvas["id"], node_id="cnd_agent"
    )
    assert node_ids == ["cnd_agent", "cnd_note"]
    # A card with no path into the selected one is not context, however near it
    # happens to sit on screen.
    assert "cnd_unrelated" not in node_ids
    assert digest["selected_node_id"] == "cnd_agent"
    assert any("霓虹灯" in (node.get("text") or "") for node in digest["nodes"])


def test_the_context_walk_is_bounded(client: TestClient, db: Session, funded: User) -> None:
    """An unbounded walk on a large canvas builds a prompt nobody can afford
    and no context window holds."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)

    chain = agent_service.MAX_CONTEXT_DEPTH + 4
    nodes = [_agent_card()] + [
        {
            "op_id": f"op_{i}",
            "kind": "node.create",
            "node": {
                "id": f"cnd_{i}",
                "kind": "note",
                "position": {"x": i * 50, "y": 0},
                "data": {"text": f"第 {i} 层"},
            },
        }
        for i in range(chain)
    ]
    _apply(client, funded, canvas["id"], nodes)
    # A straight line: cnd_{n-1} -> cnd_{n-2} -> ... -> cnd_0 -> cnd_agent
    edges = [
        {
            "op_id": f"op_e{i}",
            "kind": "edge.create",
            "edge": {
                "id": f"cne_{i}",
                "source": f"cnd_{i + 1}",
                "target": f"cnd_{i}" if i > 0 else "cnd_agent",
            },
        }
        for i in range(chain - 1)
    ]
    edges.insert(
        0,
        {
            "op_id": "op_e_root",
            "kind": "edge.create",
            "edge": {"id": "cne_root", "source": "cnd_0", "target": "cnd_agent"},
        },
    )
    _apply(client, funded, canvas["id"], edges)

    node_ids, _ = agent_service.upstream_context(db, canvas_id=canvas["id"], node_id="cnd_agent")
    assert len(node_ids) <= agent_service.MAX_CONTEXT_NODES
    # The far end of the chain is beyond the depth cap.
    assert f"cnd_{chain - 1}" not in node_ids


# ---------------------------------------------------------------------------
# Planning and pricing
# ---------------------------------------------------------------------------


def test_a_plan_is_priced_and_waits_for_confirmation(
    client: TestClient, db: Session, funded: User
) -> None:
    """Nothing is charged until the user taps confirm.

    The quote is what makes that tap informed, so it has to be on the run
    before it is offered.
    """
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])

    run = _plan(client, funded, canvas["id"])
    assert run["status"] == CanvasAgentRunStatus.AWAITING_CONFIRM
    assert run["tasks"], "the fake planner produces one task"
    assert run["quoted_credits"] > 0
    assert all(task["status"] == CanvasAgentTaskStatus.PLANNED for task in run["tasks"])
    # No job exists yet, so no credits are reserved.
    assert db.query(GenerationJob).count() == 0


def test_the_landing_slot_is_reserved_at_plan_time(
    client: TestClient, db: Session, funded: User
) -> None:
    """So the user is shown where output will appear, and so tasks finishing
    out of order still land where they were promised."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card(x=100, y=50)])

    run = _plan(client, funded, canvas["id"])
    drop = run["tasks"][0]["drop"]
    assert drop["x"] == 100 + agent_service.DROP_OFFSET_X
    assert drop["y"] == 50


def test_the_run_records_exactly_what_the_planner_was_shown(
    client: TestClient, db: Session, funded: User
) -> None:
    """A run that spent money must be reproducible, not a black box."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])

    run = _plan(client, funded, canvas["id"])
    assert run["context_node_ids"] == ["cnd_agent"]
    assert run["model"]


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


def test_a_plan_may_not_raise_the_quality_tier_the_user_chose(
    client: TestClient, db: Session, funded: User
) -> None:
    """Otherwise "make me a few options" quietly becomes a cinematic bill."""
    tasks = agent_service._sanitise_plan(
        {"tasks": [{"operation": "text_to_image", "prompt": "x", "quality_tier": "cinematic"}]},
        digest={"nodes": []},
        tier_ceiling=QualityTier.PREVIEW.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert [task.quality_tier for task in tasks] == [QualityTier.PREVIEW.value]


def test_a_plan_may_lower_the_quality_tier(client: TestClient, db: Session, funded: User) -> None:
    """The cap is one-directional: a cheap draft is a legitimate choice."""
    tasks = agent_service._sanitise_plan(
        {"tasks": [{"operation": "text_to_image", "prompt": "x", "quality_tier": "preview"}]},
        digest={"nodes": []},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert [task.quality_tier for task in tasks] == [QualityTier.PREVIEW.value]


def test_a_hallucinated_reference_is_dropped_before_it_reaches_submit(
    client: TestClient, db: Session, funded: User
) -> None:
    """`validate_generation_references` would catch ownership, but a made-up id
    should fail here as a legible domain refusal rather than surfacing from deep
    inside `submit` as a generic reference error."""
    tasks = agent_service._sanitise_plan(
        {
            "tasks": [
                {
                    "operation": "text_to_image",
                    "prompt": "x",
                    "reference_asset_ids": ["ast_never_existed"],
                }
            ]
        },
        digest={"nodes": [{"id": "n", "asset_id": "ast_real"}]},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert tasks[0].params.get("reference_asset_ids") is None


def test_an_edit_task_with_no_usable_reference_is_dropped_entirely(
    client: TestClient, db: Session, funded: User
) -> None:
    """Rewriting it to a text-to-image would silently generate something the
    user never asked for, and charge them for it."""
    tasks = agent_service._sanitise_plan(
        {
            "tasks": [
                {
                    "operation": "image_to_image",
                    "prompt": "x",
                    "reference_asset_ids": ["ast_never_existed"],
                }
            ]
        },
        digest={"nodes": []},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert tasks == []


def test_a_forced_model_from_the_planner_is_ignored(
    client: TestClient, db: Session, funded: User
) -> None:
    """Routing exists to keep cost and availability deterministic; letting the
    model pick its own endpoint gives that up for nothing."""
    tasks = agent_service._sanitise_plan(
        {
            "tasks": [
                {
                    "operation": "text_to_image",
                    "prompt": "x",
                    "forced_model": "some-expensive-model",
                }
            ]
        },
        digest={"nodes": []},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert "forced_model" not in tasks[0].params


def test_an_unplannable_operation_is_dropped(client: TestClient, db: Session, funded: User) -> None:
    tasks = agent_service._sanitise_plan(
        {
            "tasks": [
                {"operation": "audio_generation", "prompt": "x"},
                {"operation": "text_to_image", "prompt": "keep me"},
            ]
        },
        digest={"nodes": []},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=4,
        origin=(0, 0),
    )
    assert [task.operation for task in tasks] == ["text_to_image"]


def test_the_task_count_is_capped(client: TestClient, db: Session, funded: User) -> None:
    tasks = agent_service._sanitise_plan(
        {"tasks": [{"operation": "text_to_image", "prompt": f"p{i}"} for i in range(10)]},
        digest={"nodes": []},
        tier_ceiling=QualityTier.STANDARD.value,
        max_tasks=2,
        origin=(0, 0),
    )
    assert len(tasks) == 2


def test_an_empty_plan_fails_the_run_rather_than_awaiting_a_confirmation(
    client: TestClient, db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken planner must produce nothing and charge nothing — the same
    "safe by default" rule `quality.py` follows in the other direction."""
    monkeypatch.setattr(agent_service, "_sanitise_plan", lambda *a, **k: [])
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])

    run = _plan(client, funded, canvas["id"])
    assert run["status"] == CanvasAgentRunStatus.FAILED
    assert run["failure_code"] == "NO_TASKS"
    assert run["quoted_credits"] == 0
    assert db.query(GenerationJob).count() == 0


def test_planning_is_refused_when_the_canvas_has_no_room(
    client: TestClient, db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked before a credit moves. A job that succeeds, captures credits and
    then has nowhere to put its result is the worst outcome available."""
    from app.domain.canvas import graph_service

    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    monkeypatch.setattr(graph_service, "node_count", lambda *a, **k: graph_service.MAX_NODES)

    response = client.post(
        f"/v1/canvas-projects/{canvas['id']}/agent-runs",
        json={"agent_node_id": "cnd_agent", "goal": "生成"},
        headers=auth_header(funded),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


def test_confirming_submits_one_job_per_task(client: TestClient, db: Session, funded: User) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])

    confirmed = client.post(
        f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded)
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == CanvasAgentRunStatus.RUNNING
    assert all(task["generation_job_id"] for task in body["tasks"])
    assert db.query(GenerationJob).count() == len(body["tasks"])


def test_confirming_actually_hands_the_jobs_to_the_broker(
    client: TestClient, db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submitting reserves credits; dispatching is what makes anything happen.

    An earlier version guarded the enqueue on `status == QUEUED`, which
    `jobs_service.submit` never leaves a job at — so every Agent run charged
    the user and then sat untouched until `expire_stale_jobs` reclaimed it.
    Asserting the jobs *exist* did not catch that; only asserting they were
    handed over does.
    """
    from app.domain.jobs import dispatch as job_dispatch

    handed: list[str] = []
    monkeypatch.setattr(job_dispatch, "enqueue", lambda job: handed.append(job.id))

    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])

    confirmed = client.post(
        f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded)
    )
    assert confirmed.status_code == 200, confirmed.text
    submitted = [task["generation_job_id"] for task in confirmed.json()["tasks"]]
    assert handed and sorted(handed) == sorted(submitted)


def test_confirming_twice_does_not_reserve_credits_twice(
    client: TestClient, db: Session, funded: User
) -> None:
    """A double-tapped confirm is the realistic failure, and credits are the
    thing it must not duplicate."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])

    first = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded))
    assert first.status_code == 200
    jobs_after_first = db.query(GenerationJob).count()

    second = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded))
    # Refused outright by the conditional transition, rather than silently
    # submitting a second set.
    assert second.status_code == 422
    assert db.query(GenerationJob).count() == jobs_after_first


def _balance(db: Session, user: User) -> int:
    db.expire_all()
    return credits_service.get_or_create_account(db, user.id).available_balance


def test_a_keyed_confirm_retry_replays_the_original_and_charges_once(
    client: TestClient, db: Session, funded: User
) -> None:
    """A client that timed out does not know whether the confirm landed. Its
    retry must get the answer the first call got — not an error for a spend
    that did happen, and not a second spend."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])
    before = _balance(db, funded)
    headers = {**auth_header(funded), "Idempotency-Key": "confirm-attempt-1"}

    first = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=headers)
    assert first.status_code == 200, first.text
    charged = before - _balance(db, funded)
    assert charged == run["quoted_credits"] > 0
    jobs_after_first = db.query(GenerationJob).count()

    retried = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json() == first.json()
    assert db.query(GenerationJob).count() == jobs_after_first
    assert before - _balance(db, funded) == charged


def test_a_retry_that_raced_the_original_still_gets_its_response(
    client: TestClient, db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry sent while the original is still in flight finds no record,
    then loses the run's status transition once the original commits. It must
    still be answered from the original's record rather than refused."""
    from app.api import idempotency

    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])
    headers = {**auth_header(funded), "Idempotency-Key": "confirm-attempt-race"}

    first = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=headers)
    assert first.status_code == 200, first.text

    # Replay the interleaving: the retry's up-front lookup ran before the
    # original's record existed.
    real_find_replay = idempotency.find_replay
    lookups: list[int] = []

    def find_replay_after_first_miss(*args, **kwargs):  # type: ignore[no-untyped-def]
        lookups.append(1)
        return None if len(lookups) == 1 else real_find_replay(*args, **kwargs)

    monkeypatch.setattr(idempotency, "find_replay", find_replay_after_first_miss)
    retried = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json() == first.json()
    assert len(lookups) == 2


def test_a_confirm_key_reused_for_another_run_is_a_conflict(
    client: TestClient, db: Session, funded: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card("cnd_agent_a", x=100)])
    _apply(client, funded, canvas["id"], [_agent_card("cnd_agent_b", x=600)])
    run_a = _plan(client, funded, canvas["id"], node_id="cnd_agent_a")
    run_b = _plan(client, funded, canvas["id"], node_id="cnd_agent_b")
    headers = {**auth_header(funded), "Idempotency-Key": "confirm-attempt-reused"}

    assert (
        client.post(f"/v1/canvas-agent-runs/{run_a['id']}/confirm", headers=headers).status_code
        == 200
    )
    reused = client.post(f"/v1/canvas-agent-runs/{run_b['id']}/confirm", headers=headers)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_an_unkeyed_second_confirm_is_still_refused(
    client: TestClient, db: Session, funded: User
) -> None:
    """Replay is opt-in by key. Without one, a second confirm is a double tap,
    and the conditional transition refuses it as before."""
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])
    keyed = {**auth_header(funded), "Idempotency-Key": "confirm-attempt-2"}

    first = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=keyed)
    assert first.status_code == 200
    second = client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded))
    assert second.status_code == 422


def test_cancelling_stops_the_run_and_its_tasks(
    client: TestClient, db: Session, funded: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])
    client.post(f"/v1/canvas-agent-runs/{run['id']}/confirm", headers=auth_header(funded))

    cancelled = client.post(
        f"/v1/canvas-agent-runs/{run['id']}/cancel", headers=auth_header(funded)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == CanvasAgentRunStatus.CANCELLED
    db.expire_all()
    statuses = {task.status for task in db.query(CanvasAgentTask).all()}
    assert statuses == {CanvasAgentTaskStatus.CANCELLED}


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def test_an_outsider_can_neither_plan_nor_read_a_run(
    client: TestClient, db: Session, funded: User, remixer: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    run = _plan(client, funded, canvas["id"])

    assert (
        client.post(
            f"/v1/canvas-projects/{canvas['id']}/agent-runs",
            json={"agent_node_id": "cnd_agent", "goal": "生成"},
            headers=auth_header(remixer),
        ).status_code
        == 404
    )
    assert (
        client.get(f"/v1/canvas-agent-runs/{run['id']}", headers=auth_header(remixer)).status_code
        == 404
    )


def test_agent_runs_are_gated_on_the_feature_flag(
    client: TestClient, db: Session, funded: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    canvas = _canvas(client, funded)
    _apply(client, funded, canvas["id"], [_agent_card()])
    _set_canvas_flag(db, enabled=False)
    db.commit()

    response = client.post(
        f"/v1/canvas-projects/{canvas['id']}/agent-runs",
        json={"agent_node_id": "cnd_agent", "goal": "生成"},
        headers=auth_header(funded),
    )
    assert response.status_code == 404
