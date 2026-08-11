"""Domain operations: moderation, user administration and credit operations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.domain.credits import service as credits_service
from app.models import (
    AuditLog,
    CreationSkill,
    CreditLedgerEntry,
    ModerationQueueItem,
    ModerationResult,
    Notification,
    ReportCase,
    User,
    Work,
    WorkVersion,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    CreationSkillStatus,
    LedgerEntryType,
    LifecycleStatus,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    UserStatus,
    Visibility,
)
from app.platform_config import service as config_service
from app.workflows.defaults import default_graph
from tests.conftest import admin_header


@pytest.fixture
def work(db: Session, author: User) -> Work:
    item = Work(
        owner_user_id=author.id,
        visibility=Visibility.PUBLIC_REMIXABLE,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
    )
    db.add(item)
    db.flush()
    version = WorkVersion(
        work_id=item.id, version_number=1, title="待审核作品", immutable_created_at=utcnow()
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.commit()
    return item


@pytest.fixture
def queue_item(db: Session, work: Work) -> ModerationQueueItem:
    item = ModerationQueueItem(
        stage=ModerationStage.PRE_PUBLISH,
        subject_type="work",
        subject_id=work.id,
        status=ModerationStatus.NEEDS_REVIEW,
        priority=5,
    )
    db.add(item)
    db.commit()
    return item


@pytest.fixture
def skill(db: Session, author: User) -> CreationSkill:
    item = CreationSkill(
        owner_user_id=author.id,
        title="电影感夜景",
        status=CreationSkillStatus.PENDING_REVIEW,
    )
    db.add(item)
    db.commit()
    return item


@pytest.fixture
def skill_queue_item(db: Session, skill: CreationSkill) -> ModerationQueueItem:
    item = ModerationQueueItem(
        stage=ModerationStage.PRE_PUBLISH,
        subject_type="skill",
        subject_id=skill.id,
        status=ModerationStatus.NEEDS_REVIEW,
        priority=5,
    )
    db.add(item)
    db.commit()
    return item


@pytest.fixture
def report(db: Session, work: Work, remixer: User) -> ReportCase:
    case = ReportCase(
        reporter_user_id=remixer.id,
        subject_type="work",
        subject_id=work.id,
        reason="copyright",
        detail="疑似抄袭",
    )
    db.add(case)
    db.commit()
    return case


# --- moderation -----------------------------------------------------------


def test_the_queue_lists_items_needing_review(
    client: TestClient, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    body = client.get("/v1/admin/moderation/queue", headers=admin_header(reviewer)).json()
    assert queue_item.id in [i["id"] for i in body["items"]]


def test_claiming_an_item_records_the_reviewer(
    client: TestClient, db: Session, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    """Two reviewers working the same item is wasted effort and, worse, two
    conflicting verdicts."""
    response = client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/claim", headers=admin_header(reviewer)
    )
    assert response.status_code == 200

    db.refresh(queue_item)
    assert queue_item.claimed_by_user_id == reviewer.id


def test_approving_leaves_the_work_visible(
    client: TestClient, db: Session, reviewer: User, work: Work, queue_item: ModerationQueueItem
) -> None:
    response = client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.APPROVED.value,
            "reason_code": None,
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    assert work.lifecycle_status == LifecycleStatus.ACTIVE

    note = db.scalar(
        select(Notification).where(
            Notification.user_id == work.owner_user_id,
            Notification.title_key == "notification.work_approved",
        )
    )
    assert note is not None
    assert note.type == NotificationType.MODERATION


def test_rejecting_hides_rather_than_tombstones_the_work(
    client: TestClient, db: Session, reviewer: User, work: Work, queue_item: ModerationQueueItem
) -> None:
    """A reviewer's verdict must stay undoable, unlike an operator's tombstone."""
    response = client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "copyright",
            "public_message": "涉嫌侵权，已下架。",
        },
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    assert work.lifecycle_status == LifecycleStatus.HIDDEN

    note = db.scalar(
        select(Notification).where(
            Notification.user_id == work.owner_user_id,
            Notification.title_key == "notification.work_hidden",
        )
    )
    assert note is not None
    assert note.payload_json["reason"] == "涉嫌侵权，已下架。"


def test_moderation_detail_exposes_work_and_history_and_supports_restore(
    client: TestClient, db: Session, admin: User, work: Work, queue_item: ModerationQueueItem
) -> None:
    client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "copyright",
            "public_message": "涉嫌侵权，已下架。",
        },
        headers=admin_header(admin),
    )

    body = client.get(
        f"/v1/admin/moderation/queue/{queue_item.id}/detail", headers=admin_header(admin)
    ).json()
    assert body["work"]["id"] == work.id
    assert body["work"]["lifecycle_status"] == LifecycleStatus.HIDDEN
    assert body["work"]["title"] == "待审核作品"
    assert [h["status"] for h in body["history"]] == [ModerationStatus.REJECTED.value]

    response = client.post(
        f"/v1/admin/works/{work.id}/restore",
        json={"reason": "申诉成立", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    assert work.lifecycle_status == LifecycleStatus.ACTIVE
    assert db.scalar(
        select(Notification).where(
            Notification.user_id == work.owner_user_id,
            Notification.title_key == "notification.work_restored",
        )
    )


def test_rejecting_a_skill_notifies_its_owner(
    client: TestClient,
    db: Session,
    reviewer: User,
    skill: CreationSkill,
    skill_queue_item: ModerationQueueItem,
) -> None:
    response = client.post(
        f"/v1/admin/moderation/queue/{skill_queue_item.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "quality",
            "public_message": "示例效果不达标。",
        },
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(skill)
    assert skill.status == CreationSkillStatus.REJECTED

    note = db.scalar(
        select(Notification).where(
            Notification.user_id == skill.owner_user_id,
            Notification.title_key == "notification.skill_rejected",
        )
    )
    assert note is not None
    assert note.payload_json["title"] == skill.title
    assert note.payload_json["reason"] == "示例效果不达标。"


def test_taking_down_a_published_skill_notifies_its_owner(
    client: TestClient, db: Session, admin: User, skill: CreationSkill
) -> None:
    skill.status = CreationSkillStatus.PUBLISHED
    db.commit()

    response = client.post(
        f"/v1/admin/skills/{skill.id}/takedown",
        json={"reason": "涉嫌侵权", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(skill)
    assert skill.status == CreationSkillStatus.REJECTED

    note = db.scalar(
        select(Notification).where(
            Notification.user_id == skill.owner_user_id,
            Notification.title_key == "notification.skill_takedown",
        )
    )
    assert note is not None
    assert note.payload_json["reason"] == "涉嫌侵权"


def test_a_human_verdict_supersedes_rather_than_edits_the_agent_one(
    client: TestClient, db: Session, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    """The disagreement between machine and human belongs on the record."""
    db.add(
        ModerationResult(
            stage=queue_item.stage,
            subject_type="work",
            subject_id=queue_item.subject_id,
            status=ModerationStatus.NEEDS_REVIEW,
            categories_json={},
            decided_by="agent",
            created_at=utcnow(),
        )
    )
    db.commit()

    client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.APPROVED.value,
            "reason_code": None,
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )

    rows = list(
        db.scalars(
            select(ModerationResult).where(ModerationResult.subject_id == queue_item.subject_id)
        )
    )
    assert {r.decided_by for r in rows} == {"agent", "human"}


def test_a_moderation_decision_is_audited(
    client: TestClient, db: Session, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.APPROVED.value,
            "reason_code": None,
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "moderation.decide"))
    assert entry is not None
    assert entry.actor_user_id == reviewer.id


def test_reports_are_listed(client: TestClient, reviewer: User, report: ReportCase) -> None:
    body = client.get("/v1/admin/reports", headers=admin_header(reviewer)).json()
    assert report.id in [r["id"] for r in body["items"]]


def test_resolving_a_report_records_who_handled_it(
    client: TestClient, db: Session, reviewer: User, report: ReportCase
) -> None:
    response = client.post(
        f"/v1/admin/reports/{report.id}/resolve",
        json={"status": "resolved", "resolution_note": "已核实并处理"},
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(report)
    assert report.handled_by_user_id == reviewer.id
    assert report.resolution_note == "已核实并处理"


def test_duplicate_fingerprints_can_be_listed(client: TestClient, reviewer: User) -> None:
    response = client.get("/v1/admin/fingerprints/duplicates", headers=admin_header(reviewer))
    assert response.status_code == 200


def test_hiding_a_work_requires_a_reason(client: TestClient, admin: User, work: Work) -> None:
    response = client.post(
        f"/v1/admin/works/{work.id}/hide",
        json={"reason": "", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_tombstoning_keeps_the_row_for_lineage(
    client: TestClient, db: Session, admin: User, work: Work
) -> None:
    """Deleting would break every descendant's ancestry."""
    response = client.post(
        f"/v1/admin/works/{work.id}/tombstone",
        json={"reason": "版权申诉成立", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    assert db.get(Work, work.id) is not None
    assert work.lifecycle_status == LifecycleStatus.TOMBSTONE
    assert work.visibility == Visibility.PRIVATE


def test_a_hidden_work_can_be_restored(
    client: TestClient, db: Session, admin: User, work: Work
) -> None:
    client.post(
        f"/v1/admin/works/{work.id}/hide",
        json={"reason": "先下架待核实", "confirm": True},
        headers=admin_header(admin),
    )
    response = client.post(
        f"/v1/admin/works/{work.id}/restore",
        json={"reason": "申诉成立", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    assert work.lifecycle_status == LifecycleStatus.ACTIVE


# --- user administration --------------------------------------------------


def test_users_can_be_searched_by_email(client: TestClient, admin: User, author: User) -> None:
    body = client.get(
        "/v1/admin/users", params={"q": author.email}, headers=admin_header(admin)
    ).json()
    assert [u["id"] for u in body["items"]] == [author.id]


def test_users_can_be_filtered_by_status(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    author.status = UserStatus.SUSPENDED
    db.commit()

    body = client.get(
        "/v1/admin/users",
        params={"status": UserStatus.SUSPENDED.value},
        headers=admin_header(admin),
    ).json()
    assert author.id in [u["id"] for u in body["items"]]


def test_a_suspended_user_can_be_unsuspended(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    client.post(
        f"/v1/admin/users/{author.id}/suspend",
        json={"reason": "临时封禁", "confirm": True},
        headers=admin_header(admin),
    )
    response = client.post(
        f"/v1/admin/users/{author.id}/unsuspend",
        json={"reason": "申诉成立", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(author)
    assert author.status == UserStatus.ACTIVE


def test_granting_a_role_is_audited(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/roles",
        json={"roles": ["user", "reviewer"], "reason": "加入审核组", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(author)
    assert "reviewer" in author.roles

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.grant_role", AuditLog.target_id == author.id
        )
    )
    assert entry is not None
    assert entry.reason == "加入审核组"


def test_an_unknown_role_is_rejected(client: TestClient, admin: User, author: User) -> None:
    response = client.post(
        f"/v1/admin/users/{author.id}/roles",
        json={"roles": ["user", "superuser"], "reason": "测试", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_data_requests_can_be_listed(client: TestClient, admin: User) -> None:
    assert client.get("/v1/admin/data-requests", headers=admin_header(admin)).status_code == 200


# --- credit operations ----------------------------------------------------


def test_the_ledger_can_be_searched(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    credits_service.grant(db, author.id, 300, idempotency_key=new_id("grant"))
    db.commit()

    body = client.get("/v1/admin/credits/ledger", headers=admin_header(admin)).json()
    assert body["items"]


def test_one_users_ledger_can_be_isolated(
    client: TestClient, db: Session, admin: User, author: User, remixer: User
) -> None:
    credits_service.grant(db, author.id, 300, idempotency_key=new_id("g1"))
    credits_service.grant(db, remixer.id, 400, idempotency_key=new_id("g2"))
    db.commit()

    body = client.get(f"/v1/admin/users/{author.id}/credits", headers=admin_header(admin)).json()
    assert body["items"]
    assert all(entry["amount"] == 300 for entry in body["items"])


def test_the_reconciliation_report_is_available(client: TestClient, admin: User) -> None:
    response = client.get("/v1/admin/credits/reconciliation", headers=admin_header(admin))
    assert response.status_code == 200


def test_dangling_reservations_are_reported(client: TestClient, admin: User) -> None:
    """A reservation that is never captured or released is the invariant most
    worth alarming on."""
    response = client.get("/v1/admin/credits/dangling", headers=admin_header(admin))
    assert response.status_code == 200


def test_a_manual_adjustment_appends_rather_than_edits(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    """The ledger is append-only; a correction is another row."""
    credits_service.grant(db, author.id, 100, idempotency_key=new_id("grant"))
    db.commit()
    before = len(list(db.scalars(select(CreditLedgerEntry))))

    client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 50, "reason": "补偿一次失败任务", "confirm": True},
        headers=admin_header(admin),
    )

    entries = list(db.scalars(select(CreditLedgerEntry)))
    assert len(entries) == before + 1
    assert any(e.type == LedgerEntryType.ADJUSTMENT for e in entries)


def test_an_adjustment_changes_the_balance(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    before = credits_service.get_or_create_account(db, author.id).available_balance
    db.commit()

    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": 75, "reason": "补偿一次失败任务", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    after = credits_service.get_or_create_account(db, author.id).available_balance
    assert after == before + 75


def test_a_negative_adjustment_cannot_push_the_balance_below_zero(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    credits_service.get_or_create_account(db, author.id)
    db.commit()

    response = client.post(
        f"/v1/admin/users/{author.id}/credits/adjust",
        json={"amount": -1_000, "reason": "扣回错误发放", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code in (402, 409, 422)

    db.expire_all()
    account = credits_service.get_or_create_account(db, author.id)
    assert account.available_balance >= 0


def test_domain_operations_are_closed_to_anonymous_callers(client: TestClient) -> None:
    for path in ("/v1/admin/moderation/queue", "/v1/admin/users", "/v1/admin/credits/ledger"):
        assert client.get(path).status_code == 401, path


# --------------------------------------------------------------------------
# Agents and workflow bindings
# --------------------------------------------------------------------------


@pytest.fixture
def agent_roles(db: Session) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    db.commit()


def _graph_binding(agent_id: str | None) -> dict:
    """The seed graph with its `safety_check` node bound to one agent."""
    graph = default_graph()
    for node in graph["nodes"]:
        if node["type"] == "safety_check":
            node["config"] = {"agent_id": agent_id}
    return graph


def test_an_agent_can_be_created_and_is_audited(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "safety",
            "key": "video-strict",
            "display_name": "视频严格版",
            "operations": ["text_to_video"],
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key"] == "video-strict"
    assert body["is_default"] is False
    assert body["operations"] == ["text_to_video"]

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "agent_profile.create"))
    assert entry is not None and entry.target_id == body["id"]


def test_two_agents_of_one_role_cannot_share_a_handle(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    payload = {"role": "safety", "key": "strict", "display_name": "严格版"}
    assert (
        client.post(
            "/v1/admin/agent-profiles", json=payload, headers=admin_header(admin)
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/admin/agent-profiles", json=payload, headers=admin_header(admin)
        ).status_code
        == 422
    )


def test_an_agents_role_and_handle_cannot_be_renamed(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """A graph binds an agent for a specific stage, so letting the role move
    underneath it would run the wrong kind of agent there; the handle is
    frozen alongside it so audit history stays legible."""
    created = client.post(
        "/v1/admin/agent-profiles",
        json={"role": "safety", "key": "strict", "display_name": "严格版"},
        headers=admin_header(admin),
    ).json()

    response = client.patch(
        f"/v1/admin/agent-profiles/{created['id']}",
        json={"key": "renamed", "display_name": "改名了"},
        headers=admin_header(admin),
    )
    assert response.status_code == 200
    assert response.json()["key"] == "strict"
    assert response.json()["display_name"] == "改名了"


def test_the_default_agent_cannot_be_disabled(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """Disabling it would leave every unbound node with nowhere to fall back
    to but the hardcoded constant."""
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    response = client.post(
        f"/v1/admin/agent-profiles/{default.id}/disable",
        json={"reason": "测试停用默认智能体", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_publishing_a_graph_bound_to_an_unknown_agent_is_blocked(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """A silent fallback would let an operator believe their edit took
    effect when the prompt never changed."""
    response = client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={
            "name": "绑定了不存在的智能体",
            "graph": _graph_binding("aprof_nosuchagent"),
            "reason": "测试未知智能体阻断发布",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert any("aprof_nosuchagent" in message for message in errors)


def test_publishing_a_graph_bound_to_a_disabled_agent_is_blocked(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    profile = agent_skills_service.create_profile(
        db, role="safety", key="retired", display_name="停用版"
    )
    agent_skills_service.update_profile(db, profile.id, enabled=False)
    db.commit()

    response = client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={
            "name": "绑定了停用智能体",
            "graph": _graph_binding(profile.id),
            "reason": "测试停用智能体阻断发布",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_publishing_a_graph_bound_to_an_agent_of_the_wrong_role_is_blocked(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """Only reachable by hand-editing the JSON, since the console filters its
    picker by role — but running a copywriter where the pipeline expects a
    safety verdict would wave through whatever it produced."""
    copywriter = agent_skills_service.default_profile(db, "copy")
    assert copywriter is not None

    response = client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={
            "name": "安全节点绑定了文案智能体",
            "graph": _graph_binding(copywriter.id),
            "reason": "测试角色不匹配阻断发布",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert any("safety" in message for message in errors)


def test_a_capability_mismatch_warns_but_does_not_block_publishing(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """A declared capability is advice, not a constraint: reusing a video
    prompt for images may well be deliberate."""
    strict = agent_skills_service.create_profile(
        db,
        role="safety",
        key="video-strict",
        display_name="视频严格版",
        operations=["text_to_video"],
    )
    db.commit()
    graph = _graph_binding(strict.id)

    validated = client.post(
        "/v1/admin/workflow-templates/validate",
        json={"graph": graph, "operation": "text_to_image"},
        headers=admin_header(admin),
    ).json()
    assert validated["errors"] == []
    assert any("视频严格版" in message for message in validated["warnings"])

    published = client.put(
        "/v1/admin/workflow-templates/text_to_image",
        json={
            "name": "复用视频智能体",
            "graph": graph,
            "reason": "测试能力不匹配只警示",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert published.status_code == 201


def test_a_matching_capability_produces_no_warning(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    strict = agent_skills_service.create_profile(
        db,
        role="safety",
        key="video-strict",
        display_name="视频严格版",
        operations=["text_to_video"],
    )
    db.commit()

    validated = client.post(
        "/v1/admin/workflow-templates/validate",
        json={"graph": _graph_binding(strict.id), "operation": "text_to_video"},
        headers=admin_header(admin),
    ).json()
    assert validated["errors"] == []
    assert validated["warnings"] == []


def test_a_bound_agent_is_reported_as_used_by_that_operation(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """The console's "used by" badge is what tells an operator whether
    disabling an agent is safe."""
    strict = agent_skills_service.create_profile(
        db, role="safety", key="video-strict", display_name="视频严格版"
    )
    db.commit()
    client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={
            "name": "绑定严格版",
            "graph": _graph_binding(strict.id),
            "reason": "测试反查索引",
            "confirm": True,
        },
        headers=admin_header(admin),
    )

    profiles = client.get(
        "/v1/admin/agent-profiles", params={"role": "safety"}, headers=admin_header(admin)
    ).json()["items"]
    strict = next(profile for profile in profiles if profile["key"] == "video-strict")
    assert strict["used_by_operations"] == ["text_to_video"]


def test_a_prompt_published_for_one_slot_leaves_the_other_alone(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """End-to-end cover for the `intent_router` defect: the console used to
    expose one prompt chain for two unrelated calls."""
    profile = agent_skills_service.default_profile(db, "intent_router")
    assert profile is not None
    db.commit()

    for slot, text in (("classify", "档位判定"), ("select_provider", "供应商选型")):
        assert (
            client.post(
                "/v1/admin/agent-skills",
                json={
                    "profile_id": profile.id,
                    "slot": slot,
                    "prompt_template": text,
                    "reason": f"测试 {slot} 槽位",
                    "confirm": True,
                },
                headers=admin_header(admin),
            ).status_code
            == 201
        )

    for slot, text in (("classify", "档位判定"), ("select_provider", "供应商选型")):
        versions = client.get(
            "/v1/admin/agent-skills",
            params={"profile_id": profile.id, "slot": slot},
            headers=admin_header(admin),
        ).json()["items"]
        active = [row for row in versions if row["is_active"]]
        assert len(active) == 1
        assert active[0]["prompt_template"] == text


def test_agent_nodes_declare_their_prompt_slots(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """Without this the console cannot know to render two editor tabs."""
    nodes = client.get("/v1/admin/agent-nodes", headers=admin_header(admin)).json()["items"]
    by_role = {node["role"]: node for node in nodes}
    assert [slot["key"] for slot in by_role["intent_router"]["prompt_slots"]] == [
        "classify",
        "select_provider",
    ]
    assert [slot["key"] for slot in by_role["safety"]["prompt_slots"]] == ["default"]


def test_a_viewer_can_read_agents_but_not_create_them(
    client: TestClient, reviewer: User, admin: User, agent_roles: None
) -> None:
    assert client.get("/v1/admin/agent-profiles", headers=admin_header(reviewer)).status_code == 200
    assert (
        client.post(
            "/v1/admin/agent-profiles",
            json={"role": "safety", "key": "nope", "display_name": "不该成功"},
            headers=admin_header(reviewer),
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------
# Creating an agent: role presets, model pins and media candidates
# --------------------------------------------------------------------------


def _seed_endpoints(db: Session) -> None:
    """One general endpoint to pin a judgment agent to, and one media
    endpoint a video creative agent can route through."""
    config_service.set_value(
        db,
        "llm_providers",
        {
            "endpoints": {
                "general-ep": {
                    "name": "通用端点",
                    "base_url": "https://general.invalid",
                    "api_key": "k",
                    "kind": "general",
                    "models": ["kimi-k3"],
                    "role": "primary",
                },
                "video-ep": {
                    "name": "视频端点",
                    "base_url": "https://video.invalid",
                    "api_key": "k",
                    "kind": "media",
                    "model": "minimax-h3",
                    "input_modalities": ["text"],
                    "output_modalities": ["video"],
                },
                "image-ep": {
                    "name": "图片端点",
                    "base_url": "https://image.invalid",
                    "api_key": "k",
                    "kind": "media",
                    "model": "gpt-image-1",
                    "input_modalities": ["text"],
                    "output_modalities": ["image"],
                },
            }
        },
        actor_user_id=None,
        note="test bootstrap",
    )


def test_the_role_dropdown_is_served_from_the_preset_catalogue(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """The console must not accept a free-text role: one no node type invokes
    would produce an agent that never runs."""
    presets = client.get("/v1/admin/agent-node-presets", headers=admin_header(admin)).json()[
        "items"
    ]
    by_role = {preset["role"]: preset for preset in presets}

    assert by_role["safety"]["category"] == "judgment"
    assert by_role["video_creative"]["category"] == "creative"
    assert set(by_role["video_creative"]["operations"]) == {
        "text_to_video",
        "image_to_video",
        "video_to_video",
    }
    assert by_role["safety"]["is_new"] is False
    assert by_role["video_creative"]["is_new"] is True


def test_a_role_outside_the_catalogue_is_refused(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    response = client.post(
        "/v1/admin/agent-profiles",
        json={"role": "make-believe", "key": "x", "display_name": "凭空捏造"},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_creating_the_first_agent_for_a_creative_preset_creates_its_node(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """Creative roles are not seeded — an untouched install shows only the
    five stages its workflow templates reference."""
    _seed_endpoints(db)
    assert agent_skills_service.find_node(db, "video_creative") is None

    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "video_creative",
            "key": "default",
            "display_name": "视频创作",
            "media_candidates": [
                {"endpoint_id": "video-ep", "capability": "text_to_video", "weight": 120}
            ],
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "creative"
    assert body["media_candidates"] == [
        {"endpoint_id": "video-ep", "capability": "text_to_video", "weight": 120}
    ]
    # Operations follow the preset rather than the caller.
    assert set(body["operations"]) == {"text_to_video", "image_to_video", "video_to_video"}

    node = agent_skills_service.find_node(db, "video_creative")
    assert node is not None and node.category == "creative"


def test_a_creative_agent_cannot_claim_a_capability_its_role_excludes(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """The whole point of filtering the picker by preset: a video agent
    offering the routing agent an image route it was never written for."""
    _seed_endpoints(db)
    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "video_creative",
            "key": "wrong-modality",
            "display_name": "串了模态",
            "media_candidates": [
                {"endpoint_id": "image-ep", "capability": "text_to_image", "weight": 100}
            ],
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_creative_agent_needs_at_least_one_media_candidate(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """No candidates is not half-configured, it is a route the router can
    never satisfy."""
    _seed_endpoints(db)
    response = client.post(
        "/v1/admin/agent-profiles",
        json={"role": "video_creative", "key": "empty", "display_name": "没有候选"},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_judgment_agent_can_pin_a_default_and_backup_model(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    _seed_endpoints(db)
    created = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "safety",
            "key": "pinned",
            "display_name": "钉模型版",
            "default_endpoint_id": "general-ep",
            "max_tokens": 2048,
            "temperature": 0.1,
        },
        headers=admin_header(admin),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["default_endpoint_id"] == "general-ep"
    assert body["max_tokens"] == 2048
    assert body["temperature"] == pytest.approx(0.1)

    # An empty string is how the console goes back to the shared pool.
    cleared = client.patch(
        f"/v1/admin/agent-profiles/{body['id']}",
        json={"default_endpoint_id": ""},
        headers=admin_header(admin),
    )
    assert cleared.status_code == 200
    assert cleared.json()["default_endpoint_id"] is None


def test_pinning_a_model_that_is_not_an_enabled_general_endpoint_is_refused(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """A media endpoint serves the router's catalogue and is never reachable
    from the LLM failover pool."""
    _seed_endpoints(db)
    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "safety",
            "key": "wrong-kind",
            "display_name": "钉错端点",
            "default_endpoint_id": "video-ep",
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_backup_model_without_a_default_is_refused(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """It would silently become the primary."""
    _seed_endpoints(db)
    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "safety",
            "key": "backup-only",
            "display_name": "只有备用",
            "backup_endpoint_id": "general-ep",
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_judgment_agent_cannot_bind_media_candidates(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    _seed_endpoints(db)
    response = client.post(
        "/v1/admin/agent-profiles",
        json={
            "role": "safety",
            "key": "confused",
            "display_name": "混淆类别",
            "media_candidates": [
                {"endpoint_id": "video-ep", "capability": "text_to_video", "weight": 100}
            ],
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_skill_templates_are_filtered_to_what_suits_the_agent(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """The editor's dropdown must not offer a creative brief to a safety
    agent, nor another role's prompt."""
    templates = client.get(
        "/v1/admin/agent-skill-templates",
        params={"category": "judgment", "role": "safety"},
        headers=admin_header(admin),
    ).json()["items"]

    keys = [template["key"] for template in templates]
    assert "safety-default" in keys
    assert "creative-brief" not in keys
    assert "planner-default" not in keys
    # The role's own template sorts ahead of the generic ones.
    assert keys[0] == "safety-default"


def test_a_shipped_template_carries_the_prompt_the_code_actually_uses(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """A template that drifted from the module constant would quietly change
    behaviour the first time someone loaded it."""
    from app.agents import safety

    templates = client.get(
        "/v1/admin/agent-skill-templates",
        params={"role": "safety"},
        headers=admin_header(admin),
    ).json()["items"]
    shipped = next(template for template in templates if template["key"] == "safety-default")
    assert shipped["prompt_template"] == safety.SYSTEM_PROMPT
