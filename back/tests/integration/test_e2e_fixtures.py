"""`app.scripts.e2e_fixtures`: the rows the Playwright suites walk.

The e2e specs assert on what these rows look like from the outside, so the
contract here is the part a spec cannot see: a re-run adds nothing, and it
puts back exactly the state a spec run changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.access import service as access_service
from app.domain.credits import service as credits_service
from app.models import (
    AccessGrant,
    CreationSkill,
    Draft,
    GenerationJob,
    Like,
    SystemLog,
    Work,
    WorkVersion,
)
from app.models.enums import JobStatus, LifecycleStatus, Visibility
from app.scripts import e2e_fixtures
from app.scripts import seed as seed_script


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    keys: list[str] = []
    monkeypatch.setattr(
        e2e_fixtures.s3, "put_object", lambda key, payload, content_type=None: keys.append(key)
    )
    return keys


@pytest.fixture
def seeded(db: Session) -> dict:
    return seed_script._seed_users(db)


def _title(db: Session, work_id: str) -> str:
    version = db.scalar(select(WorkVersion).where(WorkVersion.work_id == work_id))
    assert version is not None
    return version.title


def test_it_plants_what_the_specs_look_for(db: Session, seeded: dict, uploads: list[str]) -> None:
    manifest = e2e_fixtures.run(db)

    free_remix = db.get(Work, manifest.free_remix_work_id)
    assert free_remix is not None
    assert _title(db, free_remix.id) == e2e_fixtures.FREE_REMIX_TITLE
    assert free_remix.visibility == Visibility.PUBLIC_REMIXABLE
    assert free_remix.owner_user_id == seeded["mizuki"].id

    withdrawn = db.get(Work, manifest.withdrawn_work_id)
    assert withdrawn is not None
    assert withdrawn.lifecycle_status == LifecycleStatus.TOMBSTONE
    assert withdrawn.visibility == Visibility.PRIVATE

    paid = db.get(Work, manifest.paid_work_id)
    assert paid is not None and paid.access_credits == e2e_fixtures.PAID_WORK_CREDITS

    skill = db.get(CreationSkill, manifest.paid_skill_id)
    assert skill is not None and skill.access_credits == e2e_fixtures.PAID_SKILL_CREDITS

    draft = db.get(Draft, manifest.draft_id)
    assert draft is not None
    assert draft.user_id == seeded["mizuki"].id
    assert draft.published_work_id is None
    assert draft.output_asset_id is not None

    failed = db.get(GenerationJob, manifest.failed_job_id)
    assert failed is not None and failed.status == JobStatus.FAILED
    log = db.scalar(select(SystemLog).where(SystemLog.job_id == failed.id))
    assert log is not None and log.event == e2e_fixtures.FAILED_JOB_LOG_EVENT

    # Every placeholder goes under one prefix, with a key that is stable
    # across runs, so the bucket does not collect a copy per run.
    assert uploads and all(key.startswith("e2e-fixtures/") for key in uploads)


def test_a_second_run_adds_nothing(db: Session, seeded: dict, uploads: list[str]) -> None:
    first = e2e_fixtures.run(db)
    works = db.scalar(select(func.count()).select_from(Work))
    jobs = db.scalar(select(func.count()).select_from(GenerationJob))
    uploaded = len(uploads)

    second = e2e_fixtures.run(db)

    assert second == first
    assert db.scalar(select(func.count()).select_from(Work)) == works
    assert db.scalar(select(func.count()).select_from(GenerationJob)) == jobs
    assert len(uploads) == uploaded


def test_a_run_puts_back_what_the_specs_change(
    db: Session, seeded: dict, uploads: list[str]
) -> None:
    manifest = e2e_fixtures.run(db)
    linhai = seeded["linhai"]
    free_remix = db.get(Work, manifest.free_remix_work_id)
    assert free_remix is not None

    # What the login-wall spec leaves behind.
    db.add(Like(user_id=linhai.id, work_id=free_remix.id))
    free_remix.like_count += 1
    db.flush()

    e2e_fixtures.run(db)

    assert db.scalar(select(Like).where(Like.work_id == free_remix.id)) is None
    assert free_remix.like_count == 0


def test_a_bought_paid_work_is_superseded_not_refunded(
    db: Session, seeded: dict, uploads: list[str]
) -> None:
    """A purchase's ledger key is one per buyer and subject, so the same work
    can never be bought twice. Deleting the grant to "reset" it only moves the
    failure to the next unlock; the next run must offer a work not yet bought."""
    mizuki = seeded["mizuki"]
    first = e2e_fixtures.run(db)
    access_service.unlock_work(db, buyer_user_id=mizuki.id, work_id=first.paid_work_id)
    db.flush()

    second = e2e_fixtures.run(db)

    assert second.paid_work_id != first.paid_work_id
    superseded = db.get(Work, first.paid_work_id)
    assert superseded is not None
    assert superseded.lifecycle_status == LifecycleStatus.TOMBSTONE
    assert superseded.visibility == Visibility.PRIVATE
    # The purchase that happened stays on the books.
    assert (
        db.scalar(select(AccessGrant).where(AccessGrant.subject_id == first.paid_work_id))
        is not None
    )
    # And the new one can actually be bought — the step the e2e spec takes.
    assert (
        access_service.unlock_work(db, buyer_user_id=mizuki.id, work_id=second.paid_work_id)
        is not None
    )
    balance = credits_service.get_or_create_account(db, mizuki.id).available_balance
    assert balance >= e2e_fixtures.BUYER_BALANCE_FLOOR - e2e_fixtures.PAID_WORK_CREDITS

    # Without a purchase in between, the paid work stays put.
    third = e2e_fixtures.run(db)
    assert e2e_fixtures.run(db).paid_work_id == third.paid_work_id


def test_it_refuses_to_run_without_the_seed_accounts(db: Session, uploads: list[str]) -> None:
    with pytest.raises(RuntimeError, match="make seed"):
        e2e_fixtures.run(db)


def test_it_refuses_to_run_in_production(
    db: Session, seeded: dict, uploads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production", raising=False)
    with pytest.raises(RuntimeError, match="拒绝在生产环境"):
        e2e_fixtures.run(db)
    assert uploads == []
