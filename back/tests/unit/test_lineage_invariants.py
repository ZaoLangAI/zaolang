"""Creative chain invariants."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import Conflict
from app.domain.licensing import service as licensing
from app.domain.lineage import service as lineage
from app.models import User, WorkVersion
from app.models.enums import LifecycleStatus
from tests.factories import make_work


def _chain(db: Session, users: list[User], length: int) -> list[WorkVersion]:
    """Builds a linear chain: users[i] remixes the version above."""
    versions: list[WorkVersion] = []
    work, version = make_work(db, users[0], title="第 0 层")
    versions.append(version)

    for level in range(1, length):
        owner = users[level % len(users)]
        _child_work, child_version = make_work(db, owner, title=f"第 {level} 层")
        parent_work = work if level == 1 else None
        source_work = parent_work or db.get(type(work), versions[-1].work_id)
        assert source_work is not None
        snapshot = licensing.capture_license_snapshot(
            db, source_version=versions[-1], work=source_work
        )
        lineage.create_edge(
            db,
            parent_version_id=versions[-1].id,
            child_version_id=child_version.id,
            parent_author_snapshot=licensing.author_snapshot(db, source_work),
            license_snapshot_id=snapshot.id,
            workflow_version_id=None,
            reused_asset_ids=[],
            created_by_user_id=owner.id,
        )
        versions.append(child_version)
    return versions


def test_edge_records_depth_from_the_parent(db: Session, author: User, remixer: User) -> None:
    versions = _chain(db, [author, remixer], 4)

    edges = lineage.ancestors(db, versions[-1].id)

    assert [e.depth for e in edges] == [3, 2, 1]


def test_a_version_can_have_at_most_one_parent_edge(
    db: Session, author: User, remixer: User
) -> None:
    """One remix, one provenance record: forks create new versions instead."""
    work, parent = make_work(db, author)
    _, child = make_work(db, remixer)
    snapshot = licensing.capture_license_snapshot(db, source_version=parent, work=work)
    common = {
        "parent_version_id": parent.id,
        "child_version_id": child.id,
        "parent_author_snapshot": licensing.author_snapshot(db, work),
        "license_snapshot_id": snapshot.id,
        "workflow_version_id": None,
        "reused_asset_ids": [],
        "created_by_user_id": remixer.id,
    }
    lineage.create_edge(db, **common)

    with pytest.raises(Conflict):
        lineage.create_edge(db, **common)


def test_parent_version_cannot_be_deleted_while_cited(
    db: Session, author: User, remixer: User
) -> None:
    """RESTRICT on the parent FK is what makes the chain unbreakable."""
    versions = _chain(db, [author, remixer], 2)
    parent = versions[0]

    db.delete(parent)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ancestors_walk_stops_at_the_original(db: Session, author: User, remixer: User) -> None:
    versions = _chain(db, [author, remixer], 3)

    edges = lineage.ancestors(db, versions[-1].id)

    assert edges[-1].parent_work_version_id == versions[0].id


def test_descendants_finds_the_whole_subtree(db: Session, author: User, remixer: User) -> None:
    versions = _chain(db, [author, remixer], 4)

    edges = lineage.descendants(db, versions[0].id)

    assert len(edges) == 3


def test_tombstoned_ancestor_keeps_its_slot_but_hides_content(
    db: Session, author: User, remixer: User
) -> None:
    """Deleting a parent must not orphan descendants."""
    versions = _chain(db, [author, remixer], 3)
    root_work = db.get(type(db.get(WorkVersion, versions[0].id).work), versions[0].work_id)  # type: ignore[union-attr]
    assert root_work is not None
    root_work.lifecycle_status = LifecycleStatus.TOMBSTONE
    db.flush()

    tree = lineage.build_tree(db, versions[0].id)

    assert tree.is_tombstone is True
    assert tree.title == ""
    assert len(tree.children) == 1
    assert tree.children[0].is_tombstone is False


def test_tree_preserves_historical_author_attribution(
    db: Session, author: User, remixer: User
) -> None:
    versions = _chain(db, [author, remixer], 2)

    tree = lineage.build_tree(db, versions[0].id)

    assert tree.children[0].author["handle"] == "author"


def test_referenced_version_is_detected(db: Session, author: User, remixer: User) -> None:
    versions = _chain(db, [author, remixer], 2)

    assert lineage.is_referenced_by_descendants(db, versions[0].id) is True
    assert lineage.is_referenced_by_descendants(db, versions[1].id) is False


def test_ancestor_authors_are_deduplicated_nearest_first(
    db: Session, author: User, remixer: User
) -> None:
    versions = _chain(db, [author, remixer], 5)

    author_ids = lineage.ancestor_author_ids(db, versions[-1].id, max_levels=3)

    assert len(author_ids) == len(set(author_ids))
    assert author_ids[0] in {author.id, remixer.id}
