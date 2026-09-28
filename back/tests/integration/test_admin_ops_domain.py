"""Domain operations: moderation, user administration and credit operations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound
from app.domain.jobs import service as jobs_service
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
    WorkAppeal,
    WorkVersion,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    AppealStatus,
    CreationSkillStatus,
    JobOrigin,
    JobStatus,
    LedgerEntryType,
    LifecycleStatus,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Operation,
    QualityTier,
    UserStatus,
    Visibility,
)
from app.platform_config import service as config_service
from app.workflows.defaults import default_graph
from tests.conftest import admin_header
from tests.factories import make_work


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


@pytest.fixture
def appeal(db: Session, work: Work) -> WorkAppeal:
    work.lifecycle_status = LifecycleStatus.HIDDEN
    work.hide_reason = "疑似侵权"
    db.add(work)
    item = WorkAppeal(
        work_id=work.id,
        owner_user_id=work.owner_user_id,
        reason="这是我的原创作品，附创作过程录屏。",
    )
    db.add(item)
    db.commit()
    return item


# --- moderation -----------------------------------------------------------


def test_the_queue_lists_items_needing_review(
    client: TestClient, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    body = client.get("/v1/admin/moderation/queue", headers=admin_header(reviewer)).json()
    assert queue_item.id in [i["id"] for i in body["items"]]


def test_the_queue_lists_only_works_and_hides_skills(
    client: TestClient,
    reviewer: User,
    queue_item: ModerationQueueItem,
    skill_queue_item: ModerationQueueItem,
) -> None:
    body = client.get("/v1/admin/moderation/queue", headers=admin_header(reviewer)).json()
    ids = [i["id"] for i in body["items"]]
    types = {i["subject_type"] for i in body["items"]}
    assert queue_item.id in ids
    assert skill_queue_item.id not in ids
    assert types <= {"work"}


def test_the_queue_filters_by_title_and_implicit_approved_status(
    client: TestClient, db: Session, reviewer: User, author: User, queue_item: ModerationQueueItem
) -> None:
    approved, _ = make_work(db, author, title="已上线霓虹港")
    db.commit()

    inbox = client.get(
        "/v1/admin/moderation/queue",
        params={"status": ModerationStatus.NEEDS_REVIEW.value},
        headers=admin_header(reviewer),
    ).json()
    inbox_subjects = {i["subject_id"] for i in inbox["items"]}
    assert queue_item.subject_id in inbox_subjects
    assert approved.id not in inbox_subjects

    approved_page = client.get(
        "/v1/admin/moderation/queue",
        params={"status": ModerationStatus.APPROVED.value, "title": "霓虹港"},
        headers=admin_header(reviewer),
    ).json()
    assert any(i["subject_id"] == approved.id for i in approved_page["items"])
    assert all("霓虹港" in (i["preview_title"] or "") for i in approved_page["items"])


def test_the_queue_pages_by_cursor_without_skipping_or_repeating(
    client: TestClient, db: Session, reviewer: User, author: User
) -> None:
    for index in range(5):
        make_work(db, author, title=f"分页作品 {index}")
    db.commit()

    first = client.get(
        "/v1/admin/moderation/queue",
        params={"limit": 2, "status": ModerationStatus.APPROVED.value},
        headers=admin_header(reviewer),
    ).json()
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = client.get(
        "/v1/admin/moderation/queue",
        params={
            "limit": 2,
            "status": ModerationStatus.APPROVED.value,
            "cursor": first["next_cursor"],
        },
        headers=admin_header(reviewer),
    ).json()

    first_ids = {i["id"] for i in first["items"]}
    second_ids = {i["id"] for i in second["items"]}
    assert first_ids.isdisjoint(second_ids)


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


def test_a_second_reviewer_cannot_claim_an_already_claimed_item(
    client: TestClient, reviewer: User, admin: User, queue_item: ModerationQueueItem
) -> None:
    client.post(f"/v1/admin/moderation/queue/{queue_item.id}/claim", headers=admin_header(reviewer))

    response = client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/claim", headers=admin_header(admin)
    )
    assert response.status_code == 409


def test_a_second_reviewer_can_decide_a_claimed_item(
    client: TestClient, db: Session, reviewer: User, admin: User, queue_item: ModerationQueueItem
) -> None:
    """Claim is advisory only — any reviewer may record the verdict."""
    client.post(f"/v1/admin/moderation/queue/{queue_item.id}/claim", headers=admin_header(reviewer))

    response = client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.APPROVED.value,
            "reason_code": None,
            "public_message": None,
        },
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    db.refresh(queue_item)
    assert queue_item.status == ModerationStatus.APPROVED


def test_the_claimant_can_still_decide_their_own_claim(
    client: TestClient, reviewer: User, queue_item: ModerationQueueItem
) -> None:
    client.post(f"/v1/admin/moderation/queue/{queue_item.id}/claim", headers=admin_header(reviewer))

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


def test_reapproving_a_rejected_work_restores_it(
    client: TestClient, db: Session, reviewer: User, work: Work, queue_item: ModerationQueueItem
) -> None:
    client.post(
        f"/v1/admin/moderation/queue/{queue_item.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "copyright",
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )
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


def test_decide_accepts_a_work_id_that_was_never_enqueued(
    client: TestClient, db: Session, reviewer: User, author: User
) -> None:
    published, _ = make_work(db, author, title="从未入队的作品")
    db.commit()

    response = client.post(
        f"/v1/admin/moderation/queue/{published.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "OTHER",
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text
    db.refresh(published)
    assert published.lifecycle_status == LifecycleStatus.HIDDEN


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


def test_moderation_detail_exposes_the_agents_categories(
    client: TestClient, db: Session, admin: User, queue_item: ModerationQueueItem
) -> None:
    """The agent's category tags are the reviewer's only view into *why* it
    flagged the subject beyond a single reason code — losing them at the API
    boundary would make the audit trail strictly less useful than the row
    already sitting in the database."""
    db.add(
        ModerationResult(
            stage=queue_item.stage,
            subject_type=queue_item.subject_type,
            subject_id=queue_item.subject_id,
            status=ModerationStatus.NEEDS_REVIEW,
            categories_json={"categories": ["sensitive_content", "violence"]},
            decided_by="agent",
            created_at=utcnow(),
        )
    )
    db.commit()

    body = client.get(
        f"/v1/admin/moderation/queue/{queue_item.id}/detail", headers=admin_header(admin)
    ).json()
    agent_entry = next(h for h in body["history"] if h["decided_by"] == "agent")
    assert agent_entry["categories"] == ["sensitive_content", "violence"]


def test_moderation_detail_surfaces_the_open_report_count(
    client: TestClient, admin: User, queue_item: ModerationQueueItem, report: ReportCase
) -> None:
    """Reports and the moderation queue are independent backlogs; a reviewer
    acting only off the agent's flag should still see that users have
    separately complained about the same subject."""
    body = client.get(
        f"/v1/admin/moderation/queue/{queue_item.id}/detail", headers=admin_header(admin)
    ).json()
    assert body["open_report_count"] == 1


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


def test_moderation_detail_surfaces_a_character_skills_reference_images_and_consent(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    """A `category=CHARACTER` skill's `params_json` is otherwise opaque to a
    reviewer — the moderation detail must resolve its reference images (not
    just `cover_url`) and confirm the owner actually captured portrait
    consent before this ever reached `PENDING_REVIEW`."""
    from app.domain.characters import service as characters_service
    from app.models import Asset
    from app.models.enums import MediaType

    asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{author.id}/{new_id('obj')}.bin",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()

    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="女主角",
        description=None,
        reference_asset_ids=[asset.id],
        voice_description=None,
    )
    characters_service.publish_character(
        db, user_id=author.id, character_id=character.id, portrait_consent=True
    )
    item = ModerationQueueItem(
        stage=ModerationStage.PRE_PUBLISH,
        subject_type="skill",
        subject_id=character.id,
        status=ModerationStatus.NEEDS_REVIEW,
        priority=5,
    )
    db.add(item)
    db.commit()

    body = client.get(
        f"/v1/admin/moderation/queue/{item.id}/detail", headers=admin_header(admin)
    ).json()

    assert body["skill"]["category"] == "character"
    assert len(body["skill"]["character_reference_assets"]) == 1
    ref = body["skill"]["character_reference_assets"][0]
    assert ref["asset_id"] == asset.id
    assert ref["url"]
    assert body["skill"]["character_portrait_consent_at"] is not None


def test_moderation_detail_exposes_a_generation_job_and_decide_does_not_hide(
    client: TestClient, db: Session, reviewer: User, admin: User, author: User
) -> None:
    """Sandbox (and other) generation_job queue items show prompt/origin;
    rejecting them only records a verdict — the output was never published."""
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        origin=JobOrigin.SANDBOX,
    )
    job = result.job
    item = ModerationQueueItem(
        stage=ModerationStage.POST_GENERATION,
        subject_type="generation_job",
        subject_id=job.id,
        status=ModerationStatus.NEEDS_REVIEW,
        priority=5,
        reason_code="SANDBOX_OUTPUT",
    )
    db.add(item)
    db.commit()

    listed = client.get("/v1/admin/moderation/queue", headers=admin_header(admin)).json()
    assert item.id not in [entry["id"] for entry in listed["items"]]

    body = client.get(
        f"/v1/admin/moderation/queue/{item.id}/detail", headers=admin_header(admin)
    ).json()
    assert body["job"]["id"] == job.id
    assert body["job"]["origin"] == JobOrigin.SANDBOX.value
    assert body["job"]["prompt"] == "雨后的东京街头"
    assert body["work"] is None
    assert body["skill"] is None

    client.post(f"/v1/admin/moderation/queue/{item.id}/claim", headers=admin_header(reviewer))
    decided = client.post(
        f"/v1/admin/moderation/queue/{item.id}/decide",
        json={
            "decision": ModerationStatus.REJECTED.value,
            "reason_code": "quality",
            "public_message": None,
        },
        headers=admin_header(reviewer),
    )
    assert decided.status_code == 200, decided.text
    db.refresh(job)
    assert job.status == JobStatus.CREATED
    verdict = db.scalar(
        select(ModerationResult).where(
            ModerationResult.subject_type == "generation_job",
            ModerationResult.subject_id == job.id,
            ModerationResult.decided_by == "human",
        )
    )
    assert verdict is not None
    assert verdict.status == ModerationStatus.REJECTED


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


def test_reports_page_by_cursor_without_skipping_or_repeating(
    client: TestClient, db: Session, reviewer: User, work: Work
) -> None:
    cases = [
        ReportCase(subject_type="work", subject_id=work.id, reason="copyright") for _ in range(3)
    ]
    db.add_all(cases)
    db.commit()

    first = client.get(
        "/v1/admin/reports", params={"limit": 2}, headers=admin_header(reviewer)
    ).json()
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = client.get(
        "/v1/admin/reports",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=admin_header(reviewer),
    ).json()

    first_ids = {r["id"] for r in first["items"]}
    second_ids = {r["id"] for r in second["items"]}
    assert first_ids.isdisjoint(second_ids)


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

    body = response.json()
    assert body["resolution_note"] == "已核实并处理"
    assert body["handled_by_user_id"] == reviewer.id
    assert body["handled_by_display_name"] == "审核"
    assert body["handled_at"] is not None


def test_report_list_surfaces_subject_preview_and_open_report_count(
    client: TestClient, db: Session, reviewer: User, work: Work, report: ReportCase
) -> None:
    """A second open report on the same subject should show up as `2` on
    both rows — reports and the moderation queue share this signal (see
    `test_moderation_detail_surfaces_the_open_report_count`), and a
    reviewer needs the work's title/owner without decoding a raw id."""
    db.add(ReportCase(subject_type="work", subject_id=work.id, reason="fraud"))
    db.commit()

    body = client.get("/v1/admin/reports", headers=admin_header(reviewer)).json()
    row = next(r for r in body["items"] if r["id"] == report.id)
    assert row["open_report_count"] == 2
    assert row["subject"]["id"] == work.id
    assert row["subject"]["owner_user_id"] == work.owner_user_id


def test_appeals_are_listed(client: TestClient, reviewer: User, appeal: WorkAppeal) -> None:
    body = client.get("/v1/admin/appeals", headers=admin_header(reviewer)).json()
    assert appeal.id in [a["id"] for a in body["items"]]


def test_appeals_page_by_cursor_without_skipping_or_repeating(
    client: TestClient, db: Session, reviewer: User, work: Work
) -> None:
    work.lifecycle_status = LifecycleStatus.HIDDEN
    db.add(work)
    appeals = [
        WorkAppeal(work_id=work.id, owner_user_id=work.owner_user_id, reason=f"申诉理由 {i}")
        for i in range(3)
    ]
    db.add_all(appeals)
    db.commit()

    first = client.get(
        "/v1/admin/appeals", params={"limit": 2}, headers=admin_header(reviewer)
    ).json()
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = client.get(
        "/v1/admin/appeals",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=admin_header(reviewer),
    ).json()

    first_ids = {a["id"] for a in first["items"]}
    second_ids = {a["id"] for a in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_granting_an_appeal_restores_the_work(
    client: TestClient, db: Session, reviewer: User, work: Work, appeal: WorkAppeal
) -> None:
    response = client.post(
        f"/v1/admin/appeals/{appeal.id}/decide",
        json={"decision": "granted", "decision_note": "已核实为原创。"},
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    db.refresh(appeal)
    assert work.lifecycle_status == LifecycleStatus.ACTIVE
    assert appeal.status == AppealStatus.GRANTED
    assert appeal.decided_by_user_id == reviewer.id


def test_denying_an_appeal_keeps_it_hidden_and_records_the_note(
    client: TestClient, db: Session, reviewer: User, work: Work, appeal: WorkAppeal
) -> None:
    response = client.post(
        f"/v1/admin/appeals/{appeal.id}/decide",
        json={"decision": "denied", "decision_note": "未提供有效证明。"},
        headers=admin_header(reviewer),
    )
    assert response.status_code == 200, response.text

    db.refresh(work)
    db.refresh(appeal)
    assert work.lifecycle_status == LifecycleStatus.HIDDEN
    assert appeal.status == AppealStatus.DENIED
    assert appeal.decision_note == "未提供有效证明。"


def test_deciding_an_already_decided_appeal_conflicts(
    client: TestClient, reviewer: User, appeal: WorkAppeal
) -> None:
    first = client.post(
        f"/v1/admin/appeals/{appeal.id}/decide",
        json={"decision": "denied", "decision_note": "未提供有效证明。"},
        headers=admin_header(reviewer),
    )
    assert first.status_code == 200

    second = client.post(
        f"/v1/admin/appeals/{appeal.id}/decide",
        json={"decision": "granted", "decision_note": "重新考虑。"},
        headers=admin_header(reviewer),
    )
    assert second.status_code == 409


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


def _graph_binding(session: Session, agent_id: str | None) -> dict:
    """The seed graph with its `safety_check` node bound to one agent."""
    graph = default_graph(session)
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


def test_the_default_agent_cannot_be_deleted(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    response = client.post(
        f"/v1/admin/agent-profiles/{default.id}/delete",
        json={"reason": "测试删除默认智能体", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422
    assert agent_skills_service.get_profile(db, default.id) is not None


def test_a_non_default_agent_can_be_deleted(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    created = client.post(
        "/v1/admin/agent-profiles",
        json={"role": "safety", "key": "throwaway", "display_name": "临时版"},
        headers=admin_header(admin),
    ).json()

    response = client.post(
        f"/v1/admin/agent-profiles/{created['id']}/delete",
        json={"reason": "测试删除智能体", "confirm": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 204

    with pytest.raises(NotFound):
        agent_skills_service.get_profile(db, created["id"])


def test_publishing_a_graph_bound_to_an_unknown_agent_is_blocked(
    client: TestClient, db: Session, admin: User, agent_roles: None
) -> None:
    """A silent fallback would let an operator believe their edit took
    effect when the prompt never changed."""
    response = client.put(
        "/v1/admin/workflow-templates/text_to_video",
        json={
            "name": "绑定了不存在的智能体",
            "graph": _graph_binding(db, "aprof_nosuchagent"),
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
            "graph": _graph_binding(db, profile.id),
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
            "graph": _graph_binding(db, copywriter.id),
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
    graph = _graph_binding(db, strict.id)

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
        json={"graph": _graph_binding(db, strict.id), "operation": "text_to_video"},
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
            "graph": _graph_binding(db, strict.id),
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
    """One general endpoint to pin a judgment agent to, and media endpoints
    that must never be pinnable as an LLM default."""
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
                    "model": "test-llm",
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
    assert by_role["safety"]["is_new"] is False


def test_a_role_with_no_node_row_yet_is_flagged_new(client: TestClient, admin: User) -> None:
    """Without the `agent_roles` fixture's seeding, no `AgentNode` rows exist
    yet, so every preset in the catalogue is a role nobody has used."""
    presets = client.get("/v1/admin/agent-node-presets", headers=admin_header(admin)).json()[
        "items"
    ]
    by_role = {preset["role"]: preset for preset in presets}
    assert by_role["safety"]["is_new"] is True


def test_a_role_outside_the_catalogue_is_refused(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    response = client.post(
        "/v1/admin/agent-profiles",
        json={"role": "make-believe", "key": "x", "display_name": "凭空捏造"},
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
        },
        headers=admin_header(admin),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["default_endpoint_id"] == "general-ep"
    # The model id comes from the catalog endpoint, not a code default.
    # Sampling is no longer looked up by model name.
    assert body["model"] == "test-llm"
    assert body["max_tokens"] is None
    assert body["temperature"] is None

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


def test_skill_templates_are_filtered_to_what_suits_the_agent(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """The editor's dropdown must not offer another role's prompt."""
    templates = client.get(
        "/v1/admin/agent-skill-templates",
        params={"category": "judgment", "role": "safety"},
        headers=admin_header(admin),
    ).json()["items"]

    keys = [template["key"] for template in templates]
    assert "safety-default" in keys
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


def test_copy_enhance_asset_templates_match_the_module_constants(
    client: TestClient, admin: User, agent_roles: None
) -> None:
    """The three image-asset polish templates must stay on the `enhance` slot
    and keep pointing at `copywriter.ENHANCE_SYSTEM_PROMPT_*` — a copied
    string here would silently diverge the first time the constant changes."""
    from app.agents import copywriter

    templates = client.get(
        "/v1/admin/agent-skill-templates",
        params={"role": "copy"},
        headers=admin_header(admin),
    ).json()["items"]
    by_key = {template["key"]: template for template in templates}

    expected = {
        "copy-enhance-character": ("character", copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER),
        "copy-enhance-cover": ("cover", copywriter.ENHANCE_SYSTEM_PROMPT_COVER),
        "copy-enhance-scene": ("scene", copywriter.ENHANCE_SYSTEM_PROMPT_SCENE),
    }
    for key, (kind, prompt) in expected.items():
        assert key in by_key, f"missing shipped template {key}"
        shipped = by_key[key]
        assert shipped["slot"] == copywriter.ENHANCE_SLOT
        assert shipped["asset_kind"] == kind
        assert shipped["prompt_template"] == prompt

    generic = by_key["copy-enhance"]
    assert generic["asset_kind"] is None
    assert generic["prompt_template"] == copywriter.ENHANCE_SYSTEM_PROMPT
    assert by_key["copy-suggest"]["asset_kind"] == "copy"
    assert by_key["copy-suggest"]["prompt_template"] == copywriter.SYSTEM_PROMPT
