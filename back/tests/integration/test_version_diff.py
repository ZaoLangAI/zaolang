"""HTTP contract for `GET /v1/work-versions/{id}/diff`.

Before this endpoint got its own visibility/remix gate, an anonymous caller
who could merely name a child version id could read a paid or view-only
work's prompt/seed straight off this endpoint — bypassing both the paywall
`POST .../unlock` enforces and the private-work 404 every other work read
goes through.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage_service
from app.models import User, Work, WorkVersion
from app.models.base import new_id
from app.models.enums import Visibility
from tests.conftest import auth_header
from tests.factories import make_work


def _link(
    db: Session,
    parent_work: Work,
    parent_version: WorkVersion,
    child_version: WorkVersion,
    *,
    created_by: str,
) -> None:
    snapshot = licensing.capture_license_snapshot(
        db, source_version=parent_version, work=parent_work
    )
    lineage_service.create_edge(
        db,
        parent_version_id=parent_version.id,
        child_version_id=child_version.id,
        parent_author_snapshot=licensing.author_snapshot(db, parent_work),
        license_snapshot_id=snapshot.id,
        workflow_version_id=None,
        reused_asset_ids=[],
        created_by_user_id=created_by,
    )


def _fund(db: Session, user: User, amount: int = 100) -> None:
    credits_service.grant(db, user.id, amount, idempotency_key=new_id("grant"))
    db.commit()


def test_anonymous_can_diff_a_public_remixable_chain(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    parent_work, parent_version = make_work(db, author, title="原作")
    _child_work, child_version = make_work(db, remixer, title="二创")
    _link(db, parent_work, parent_version, child_version, created_by=remixer.id)
    db.commit()

    response = client.get(f"/v1/work-versions/{child_version.id}/diff")
    assert response.status_code == 200, response.text

    entries = {entry["field"]: entry for entry in response.json()["entries"]}
    assert entries["title"]["changed"] is True
    assert entries["title"]["parent_value"] == "原作"
    assert entries["title"]["child_value"] == "二创"
    assert entries["prompt"]["parent_value"] == "原作"
    assert entries["prompt"]["child_value"] == "二创"


def test_diff_hides_values_for_a_locked_paid_work_until_unlocked(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    parent_work, parent_version = make_work(db, author, title="原作")
    child_work, child_version = make_work(db, author, title="付费二创", access_credits=10)
    _link(db, parent_work, parent_version, child_version, created_by=author.id)
    db.commit()

    locked = client.get(f"/v1/work-versions/{child_version.id}/diff", headers=auth_header(remixer))
    assert locked.status_code == 200, locked.text
    locked_entries = {entry["field"]: entry for entry in locked.json()["entries"]}
    # `title` is the one entry always present, and even it withholds values
    # while locked — every other field (prompt/seed/...) is dropped entirely
    # rather than merely nulled, so a locked diff can't even leak *which*
    # reusable params exist.
    assert set(locked_entries) == {"title"}
    assert locked_entries["title"]["changed"] is True
    assert locked_entries["title"]["parent_value"] is None
    assert locked_entries["title"]["child_value"] is None

    _fund(db, remixer)
    unlock = client.post(
        f"/v1/works/{child_work.id}/unlock",
        headers={**auth_header(remixer), "Idempotency-Key": new_id("idk")},
    )
    assert unlock.status_code == 200, unlock.text

    unlocked = client.get(
        f"/v1/work-versions/{child_version.id}/diff", headers=auth_header(remixer)
    )
    assert unlocked.status_code == 200, unlocked.text
    unlocked_entries = {entry["field"]: entry for entry in unlocked.json()["entries"]}
    assert unlocked_entries["title"]["parent_value"] == "原作"
    assert unlocked_entries["title"]["child_value"] == "付费二创"


def test_diff_owner_sees_full_values_on_their_own_locked_work(
    client: TestClient, db: Session, author: User
) -> None:
    parent_work, parent_version = make_work(db, author, title="原作")
    _child_work, child_version = make_work(db, author, title="付费二创", access_credits=10)
    _link(db, parent_work, parent_version, child_version, created_by=author.id)
    db.commit()

    response = client.get(f"/v1/work-versions/{child_version.id}/diff", headers=auth_header(author))
    assert response.status_code == 200, response.text
    entries = {entry["field"]: entry for entry in response.json()["entries"]}
    assert entries["title"]["child_value"] == "付费二创"


def test_diff_for_a_private_child_work_is_not_found_to_a_stranger(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    parent_work, parent_version = make_work(db, author, title="原作")
    _child_work, child_version = make_work(
        db, author, title="私密二创", visibility=Visibility.PRIVATE
    )
    _link(db, parent_work, parent_version, child_version, created_by=author.id)
    db.commit()

    stranger = client.get(
        f"/v1/work-versions/{child_version.id}/diff", headers=auth_header(remixer)
    )
    assert stranger.status_code == 404

    anonymous = client.get(f"/v1/work-versions/{child_version.id}/diff")
    assert anonymous.status_code == 404

    owner = client.get(f"/v1/work-versions/{child_version.id}/diff", headers=auth_header(author))
    assert owner.status_code == 200, owner.text
