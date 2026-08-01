"""Community surface: likes, bookmarks, collections, follows, notifications."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.publishing import service as publishing
from app.models import Follow, Notification, ReportCase, User, Work
from app.models.base import new_id
from app.models.enums import NotificationType, Operation, QualityTier, Visibility
from app.workers import pipeline
from tests.conftest import auth_header


@pytest.fixture
def work(db: Session, author: User) -> Work:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    draft = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "海面上的黎明"}
    )
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "海面上的黎明"},
        idempotency_key=new_id("idk"),
        draft_id=draft.id,
    )
    draft.latest_job_id = result.job.id
    db.flush()
    pipeline.run_generation_pipeline(db, result.job.id)
    db.refresh(draft)

    outcome = publishing.publish(
        db,
        user_id=author.id,
        draft_id=draft.id,
        title="黎明",
        description="海面上的第一道光。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        tags=["sunrise"],
        cover_asset_id=None,
        rights_confirmed=True,
    )
    db.commit()
    return outcome.work


def test_liking_increments_the_counter(
    client: TestClient, db: Session, work: Work, remixer: User
) -> None:
    response = client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    assert response.status_code == 200

    db.refresh(work)
    assert work.like_count == 1


def test_liking_twice_still_counts_once(
    client: TestClient, db: Session, work: Work, remixer: User
) -> None:
    """A double-tapped heart must not inflate the count."""
    for _ in range(3):
        client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))

    db.refresh(work)
    assert work.like_count == 1


def test_unliking_reverses_it(client: TestClient, db: Session, work: Work, remixer: User) -> None:
    client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    client.delete(f"/v1/works/{work.id}/like", headers=auth_header(remixer))

    db.refresh(work)
    assert work.like_count == 0


def test_unliking_something_never_liked_does_not_go_negative(
    client: TestClient, db: Session, work: Work, remixer: User
) -> None:
    client.delete(f"/v1/works/{work.id}/like", headers=auth_header(remixer))

    db.refresh(work)
    assert work.like_count == 0


def test_an_anonymous_caller_cannot_like(client: TestClient, work: Work) -> None:
    assert client.post(f"/v1/works/{work.id}/like").status_code == 401


def test_bookmarking_shows_up_in_your_own_list(
    client: TestClient, work: Work, remixer: User
) -> None:
    assert (
        client.post(f"/v1/works/{work.id}/bookmark", headers=auth_header(remixer)).status_code
        == 200
    )

    listed = client.get("/v1/me/bookmarks", headers=auth_header(remixer))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [work.id]


def test_bookmarks_are_private_to_the_owner(
    client: TestClient, work: Work, remixer: User, author: User
) -> None:
    client.post(f"/v1/works/{work.id}/bookmark", headers=auth_header(remixer))

    others = client.get("/v1/me/bookmarks", headers=auth_header(author))
    assert others.json()["items"] == []


def test_a_collection_holds_works(client: TestClient, work: Work, remixer: User) -> None:
    created = client.post(
        "/v1/collections",
        json={"name": "灵感", "description": None, "is_public": False},
        headers=auth_header(remixer),
    )
    assert created.status_code == 201
    collection_id = created.json()["id"]

    added = client.post(
        f"/v1/collections/{collection_id}/items",
        params={"work_id": work.id},
        headers=auth_header(remixer),
    )
    assert added.status_code == 200

    listed = client.get("/v1/collections", headers=auth_header(remixer))
    assert listed.json()["items"][0]["item_count"] == 1


def test_adding_the_same_work_twice_does_not_duplicate_it(
    client: TestClient, work: Work, remixer: User
) -> None:
    created = client.post(
        "/v1/collections",
        json={"name": "灵感", "description": None, "is_public": False},
        headers=auth_header(remixer),
    )
    collection_id = created.json()["id"]

    for _ in range(2):
        client.post(
            f"/v1/collections/{collection_id}/items",
            params={"work_id": work.id},
            headers=auth_header(remixer),
        )

    listed = client.get("/v1/collections", headers=auth_header(remixer))
    assert listed.json()["items"][0]["item_count"] == 1


def test_you_cannot_add_to_someone_elses_collection(
    client: TestClient, work: Work, remixer: User, author: User
) -> None:
    created = client.post(
        "/v1/collections",
        json={"name": "私人", "description": None, "is_public": False},
        headers=auth_header(remixer),
    )
    collection_id = created.json()["id"]

    response = client.post(
        f"/v1/collections/{collection_id}/items",
        params={"work_id": work.id},
        headers=auth_header(author),
    )
    assert response.status_code in (403, 404)


def test_following_creates_the_edge_and_notifies(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    response = client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))
    assert response.status_code == 200

    edge = db.scalar(
        select(Follow).where(
            Follow.follower_user_id == remixer.id, Follow.followed_user_id == author.id
        )
    )
    assert edge is not None

    notes = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == author.id,
                Notification.type == NotificationType.NEW_FOLLOWER,
            )
        )
    )
    assert len(notes) == 1


def test_following_twice_does_not_notify_twice(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    for _ in range(3):
        client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    notes = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == author.id,
                Notification.type == NotificationType.NEW_FOLLOWER,
            )
        )
    )
    assert len(notes) == 1


def test_you_cannot_follow_yourself(client: TestClient, author: User) -> None:
    response = client.post(f"/v1/users/{author.id}/follow", headers=auth_header(author))
    assert response.status_code == 409


def test_unfollowing_removes_the_edge(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))
    client.delete(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    edge = db.scalar(
        select(Follow).where(
            Follow.follower_user_id == remixer.id, Follow.followed_user_id == author.id
        )
    )
    assert edge is None


def test_the_profile_reports_follower_counts(
    client: TestClient, author: User, remixer: User
) -> None:
    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    profile = client.get("/v1/profiles/author", headers=auth_header(remixer))
    assert profile.status_code == 200
    body = profile.json()
    assert body["follower_count"] == 1
    assert body["viewer_following"] is True


def test_anonymous_bookmarks_are_rejected_as_unauthenticated(client: TestClient) -> None:
    """A missing session is a 401, not a 404: the endpoint exists."""
    assert client.get("/v1/me/bookmarks").status_code == 401


def test_notifications_are_only_visible_to_their_recipient(
    client: TestClient, author: User, remixer: User
) -> None:
    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    mine = client.get("/v1/notifications", headers=auth_header(author))
    assert len(mine.json()["items"]) == 1

    theirs = client.get("/v1/notifications", headers=auth_header(remixer))
    assert theirs.json()["items"] == []


def test_the_unread_count_drops_after_marking_read(
    client: TestClient, author: User, remixer: User
) -> None:
    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))
    assert (
        client.get("/v1/notifications/unread-count", headers=auth_header(author)).json()["count"]
        == 1
    )

    client.post("/v1/notifications/read", headers=auth_header(author))
    assert (
        client.get("/v1/notifications/unread-count", headers=auth_header(author)).json()["count"]
        == 0
    )


def test_marking_read_cannot_touch_someone_elses_notifications(
    client: TestClient, author: User, remixer: User
) -> None:
    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    client.post("/v1/notifications/read", headers=auth_header(remixer))

    assert (
        client.get("/v1/notifications/unread-count", headers=auth_header(author)).json()["count"]
        == 1
    )


def test_reporting_a_work_opens_a_case(
    client: TestClient, db: Session, work: Work, remixer: User
) -> None:
    response = client.post(
        "/v1/reports",
        json={
            "subject_type": "work",
            "subject_id": work.id,
            "reason": "copyright",
            "detail": "抄袭",
        },
        headers=auth_header(remixer),
    )
    assert response.status_code == 201

    case = db.scalar(select(ReportCase).where(ReportCase.subject_id == work.id))
    assert case is not None
    assert case.reporter_user_id == remixer.id


def test_a_style_preset_can_be_saved_and_applied(
    client: TestClient, work: Work, author: User, remixer: User
) -> None:
    created = client.post(
        "/v1/style-presets",
        json={
            "name": "冷调晨雾",
            "description": None,
            "params": {"prompt": "冷调晨雾", "cfg": 7},
            "is_public": True,
            "source_work_version_id": None,
        },
        headers=auth_header(author),
    )
    assert created.status_code == 201
    preset_id = created.json()["id"]

    applied = client.post(f"/v1/style-presets/{preset_id}/apply", headers=auth_header(remixer))
    assert applied.status_code == 200
    assert applied.json()["params"]["cfg"] == 7


def test_a_private_preset_is_not_readable_by_others(
    client: TestClient, author: User, remixer: User
) -> None:
    created = client.post(
        "/v1/style-presets",
        json={
            "name": "私藏",
            "description": None,
            "params": {"prompt": "私藏"},
            "is_public": False,
            "source_work_version_id": None,
        },
        headers=auth_header(author),
    )
    preset_id = created.json()["id"]

    response = client.post(f"/v1/style-presets/{preset_id}/apply", headers=auth_header(remixer))
    assert response.status_code in (403, 404)
