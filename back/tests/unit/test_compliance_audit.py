"""Audit trail and data subject rights."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import service as audit
from app.domain.compliance import service as compliance
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound, ReasonRequired
from app.domain.publishing import service as publishing
from app.models import AuditLog, LineageEdge, Profile, User, Work, WorkVersion
from app.models.base import new_id, utcnow
from app.models.enums import LifecycleStatus, UserStatus, Visibility
from app.storage import s3

# --- audit ----------------------------------------------------------------


def test_a_privileged_action_is_recorded(db: Session, admin: User) -> None:
    entry = audit.record(
        db, actor=admin, action="config.update", target_type="platform_config", target_id="pricing"
    )
    assert entry.actor_user_id == admin.id
    assert entry.action == "config.update"


def test_the_actors_roles_are_frozen_into_the_record(db: Session, admin: User) -> None:
    """A later role change must not rewrite what authority the action was taken
    under."""
    entry = audit.record(db, actor=admin, action="config.update", target_type="platform_config")
    assert "admin" in (entry.actor_roles or "")

    admin.roles = ["user"]
    db.flush()
    db.refresh(entry)
    assert "admin" in (entry.actor_roles or "")


@pytest.mark.parametrize("action", sorted(audit.REASON_REQUIRED_ACTIONS))
def test_a_high_risk_action_cannot_be_taken_without_a_reason(
    db: Session, admin: User, action: str
) -> None:
    with pytest.raises(ReasonRequired):
        audit.record(db, actor=admin, action=action, target_type="work", target_id="wrk_1")


def test_a_whitespace_only_reason_does_not_count(db: Session, admin: User) -> None:
    with pytest.raises(ReasonRequired):
        audit.record(db, actor=admin, action="credit.adjust", target_type="user", reason="   \n  ")


def test_a_high_risk_action_with_a_reason_is_accepted(db: Session, admin: User) -> None:
    entry = audit.record(
        db,
        actor=admin,
        action="credit.adjust",
        target_type="user",
        target_id="usr_1",
        reason="补偿一次供应商故障",
    )
    assert entry.reason == "补偿一次供应商故障"


def test_secrets_in_a_diff_are_redacted(db: Session, admin: User) -> None:
    """Config diffs pass through here, and a key in a readable audit row would
    outlive the rotation that was supposed to retire it."""
    entry = audit.record(
        db,
        actor=admin,
        action="config.update",
        target_type="platform_config",
        before={"llm_api_key": "sk-real-secret-value"},
        after={"llm_api_key": "sk-new-secret-value"},
    )
    serialised = json.dumps([entry.before_json, entry.after_json], ensure_ascii=False)
    assert "sk-real-secret-value" not in serialised
    assert "sk-new-secret-value" not in serialised


def test_a_system_action_without_an_actor_is_still_recorded(db: Session) -> None:
    entry = audit.record(db, actor=None, action="config.update", target_type="platform_config")
    assert entry.actor_user_id is None


def test_the_trail_is_append_only(db: Session, admin: User) -> None:
    """A correction is a new row; the original stays readable."""
    first = audit.record(
        db, actor=admin, action="work.hide", target_type="work", target_id="wrk_1", reason="误发"
    )
    second = audit.record(
        db,
        actor=admin,
        action="work.restore",
        target_type="work",
        target_id="wrk_1",
        reason="申诉成立",
    )

    rows = list(db.scalars(select(AuditLog).where(AuditLog.target_id == "wrk_1")))
    assert {r.id for r in rows} == {first.id, second.id}


def test_the_trail_can_be_searched_by_target(db: Session, admin: User) -> None:
    audit.record(db, actor=admin, action="work.hide", target_type="work", target_id="a", reason="x")
    audit.record(db, actor=admin, action="work.hide", target_type="work", target_id="b", reason="x")

    found = audit.search(db, target_id="a")
    assert [r.target_id for r in found] == ["a"]


def test_the_trail_can_be_searched_by_actor_and_action(
    db: Session, admin: User, operator: User
) -> None:
    audit.record(db, actor=admin, action="config.update", target_type="platform_config")
    audit.record(db, actor=operator, action="config.update", target_type="platform_config")

    assert len(audit.search(db, actor_user_id=admin.id, action="config.update")) == 1


def test_the_newest_entry_comes_first(db: Session, admin: User) -> None:
    audit.record(db, actor=admin, action="config.update", target_type="platform_config")
    audit.record(db, actor=admin, action="config.rollback", target_type="c", reason="回滚")

    actions = [r.action for r in audit.search(db)]
    assert actions[0] == "config.rollback"


# --- export ---------------------------------------------------------------


@pytest.fixture
def populated(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 500, idempotency_key=new_id("grant"))
    work = Work(
        owner_user_id=author.id,
        visibility=Visibility.PUBLIC_REMIXABLE,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
    )
    db.add(work)
    db.flush()
    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title="导出测试",
        immutable_created_at=utcnow(),
    )
    db.add(version)
    db.flush()
    work.current_version_id = version.id
    db.flush()
    return author


def _read_export(key: str) -> dict:
    return json.loads(s3.get_object(key))


def test_an_export_contains_the_account_and_its_works(db: Session, populated: User) -> None:
    bundle = _read_export(compliance.export_user_data(db, populated.id))
    assert bundle["account"]["email"] == populated.email
    assert [w["title"] for w in bundle["works"]] == ["导出测试"]


def test_an_export_contains_the_credit_ledger(db: Session, populated: User) -> None:
    bundle = _read_export(compliance.export_user_data(db, populated.id))
    assert bundle["credits"]["available"] == 500
    assert bundle["credits"]["ledger"]


def test_an_export_does_not_contain_the_password_hash(db: Session, populated: User) -> None:
    """A bundle the user can download must not carry a credential."""
    raw = s3.get_object(compliance.export_user_data(db, populated.id)).decode()
    assert populated.password_hash not in raw
    assert "password" not in raw.lower()


def test_exporting_an_unknown_user_is_refused(db: Session) -> None:
    with pytest.raises(NotFound):
        compliance.export_user_data(db, "usr_missing")


def test_each_export_lands_on_its_own_key(db: Session, populated: User) -> None:
    """Guessing a previous bundle's location must not be possible."""
    first = compliance.export_user_data(db, populated.id)
    second = compliance.export_user_data(db, populated.id)
    assert first != second


def test_an_export_is_only_reachable_through_a_signed_url(db: Session, populated: User) -> None:
    key = compliance.export_user_data(db, populated.id)
    url = compliance.signed_export_url(key)
    assert "Signature=" in url or "X-Amz-Signature" in url


# --- erasure --------------------------------------------------------------


def test_erasure_removes_the_identifying_fields(db: Session, populated: User) -> None:
    original_email = populated.email
    compliance.anonymise_user(db, populated.id)

    db.refresh(populated)
    assert populated.email != original_email
    assert populated.email.endswith(compliance.ANONYMISED_DOMAIN)
    assert populated.status == UserStatus.DELETED


def test_erasure_clears_the_public_profile(db: Session, populated: User) -> None:
    compliance.anonymise_user(db, populated.id)
    profile = db.scalar(select(Profile).where(Profile.user_id == populated.id))
    assert profile is not None
    assert profile.display_name == "已注销用户"
    assert profile.public_profile is False
    assert profile.bio is None


def test_erasure_invalidates_the_old_password(db: Session, populated: User) -> None:
    before = populated.password_hash
    compliance.anonymise_user(db, populated.id)
    db.refresh(populated)
    assert populated.password_hash != before


def test_erasure_tombstones_the_works_rather_than_deleting_them(
    db: Session, populated: User
) -> None:
    compliance.anonymise_user(db, populated.id)
    works = list(db.scalars(select(Work).where(Work.owner_user_id == populated.id)))
    assert works
    for work in works:
        assert work.lifecycle_status == LifecycleStatus.TOMBSTONE
        assert work.visibility == Visibility.PRIVATE
        assert work.tombstone_reason == "user_deleted"


def test_erasure_keeps_descendants_able_to_name_their_ancestor(
    db: Session, author: User, remixer: User
) -> None:
    """A child that cannot resolve its parent is exactly the unattributed remix
    the platform promises never to produce."""
    from app.domain.jobs import service as jobs_service
    from app.models.enums import Operation, QualityTier
    from app.workers import pipeline

    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("g1"))
    credits_service.grant(db, remixer.id, 5_000, idempotency_key=new_id("g2"))

    def build(user: User, source_work_id: str | None) -> publishing.PublishOutcome:
        draft = publishing.create_draft(
            db, user_id=user.id, source_work_id=source_work_id, params={"prompt": "海雾"}
        )
        job = jobs_service.submit(
            db,
            user_id=user.id,
            operation=Operation.TEXT_TO_IMAGE,
            quality_tier=QualityTier.STANDARD,
            params={"prompt": "海雾"},
            idempotency_key=new_id("idk"),
            draft_id=draft.id,
        ).job
        draft.latest_job_id = job.id
        db.flush()
        pipeline.run_generation_pipeline(db, job.id)
        db.refresh(draft)
        return publishing.publish(
            db,
            user_id=user.id,
            draft_id=draft.id,
            title="海雾",
            description=None,
            visibility=Visibility.PUBLIC_REMIXABLE,
            tags=[],
            cover_asset_id=None,
            rights_confirmed=True,
        )

    parent = build(author, None)
    child = build(remixer, parent.work.id)

    compliance.anonymise_user(db, author.id)

    edge = db.scalar(
        select(LineageEdge).where(LineageEdge.child_work_version_id == child.version.id)
    )
    assert edge is not None
    assert db.get(WorkVersion, parent.version.id) is not None
    assert edge.parent_author_snapshot_json.get("user_id") == author.id


def test_erasing_an_unknown_user_is_refused(db: Session) -> None:
    with pytest.raises(NotFound):
        compliance.anonymise_user(db, "usr_missing")


def test_erasure_is_safe_to_repeat(db: Session, populated: User) -> None:
    """Retrying a partially failed request must not error out."""
    compliance.anonymise_user(db, populated.id)
    compliance.anonymise_user(db, populated.id)
    db.refresh(populated)
    assert populated.status == UserStatus.DELETED
