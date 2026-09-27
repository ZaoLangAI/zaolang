"""An admin role on a *consumer* session is not staff access on work reads.

`OptionalUser` / `CurrentUser` only prove a consumer-audience session, so
`viewer.roles` listing an admin role (staff browsing the consumer site as
themselves) must not double as the admin-audience staff grant — the same rule
`GET /v1/assets/{id}` follows. Staff read hidden/private works via `/v1/admin`.
Before this, the work detail, lineage graph, ancestors strip and every
`_load_visible` endpoint all handed private or hidden works to such a caller.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage_service
from app.models import User, Work, WorkVersion
from app.models.enums import LifecycleStatus, Visibility
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


def test_private_work_is_not_found_to_a_consumer_admin(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    work, _ = make_work(db, author, title="私密作品", visibility=Visibility.PRIVATE)
    db.commit()

    detail = client.get(f"/v1/works/{work.id}", headers=auth_header(admin))
    assert detail.status_code == 404
    assert "私密作品" not in detail.text

    lineage = client.get(f"/v1/works/{work.id}/lineage", headers=auth_header(admin))
    assert lineage.status_code == 404

    # Every other `_load_visible` endpoint shares the same gate.
    like = client.post(f"/v1/works/{work.id}/like", headers=auth_header(admin))
    assert like.status_code == 404


def test_hidden_work_is_not_found_to_a_consumer_admin(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    work, _ = make_work(db, author, title="已隐藏作品")
    work.lifecycle_status = LifecycleStatus.HIDDEN
    db.commit()

    response = client.get(f"/v1/works/{work.id}", headers=auth_header(admin))
    assert response.status_code == 404


def test_lineage_tree_masks_a_private_descendant_from_a_consumer_admin(
    client: TestClient, db: Session, author: User, remixer: User, admin: User
) -> None:
    root_work, root_version = make_work(db, author, title="原作")
    child_work, child_version = make_work(db, remixer, title="私密二创")
    _link(db, root_work, root_version, child_version, created_by=remixer.id)
    child_work.visibility = Visibility.PRIVATE
    db.commit()

    response = client.get(f"/v1/works/{root_work.id}/lineage", headers=auth_header(admin))
    assert response.status_code == 200, response.text
    child_node = response.json()["root"]["children"][0]
    assert child_node["is_tombstone"] is True
    assert child_node["title"] == ""


def test_ancestors_mask_a_private_parent_from_a_consumer_admin(
    client: TestClient, db: Session, author: User, remixer: User, admin: User
) -> None:
    root_work, root_version = make_work(db, author, title="私密原作")
    child_work, child_version = make_work(db, remixer, title="公开二创")
    _link(db, root_work, root_version, child_version, created_by=remixer.id)
    root_work.visibility = Visibility.PRIVATE
    db.commit()

    for path in (f"/v1/works/{child_work.id}", f"/v1/works/{child_work.id}/lineage"):
        response = client.get(path, headers=auth_header(admin))
        assert response.status_code == 200, response.text
        ancestor = response.json()["ancestors"][0]
        assert ancestor["is_tombstone"] is True, path
        assert ancestor["title"] == "", path
