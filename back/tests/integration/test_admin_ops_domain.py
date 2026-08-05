"""Domain operations: moderation, user administration and credit operations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

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
