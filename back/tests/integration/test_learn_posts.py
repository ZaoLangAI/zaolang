"""`/v1/learn/posts`: submit → review → public, and who can see what on the way."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.learning import service as learning
from app.models import Asset, LearnPost, User
from app.models.base import new_id
from app.models.enums import AssetRole, LearnPostStatus, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "三步写好镜头提示词",
        "summary": "主体、动作、镜头语言。",
        "level": "beginner",
        "body_markdown": "先写主体，再写动作。",
        **overrides,
    }


def _learn_asset(db: Session, owner: User, *, role: AssetRole = AssetRole.LEARN_MEDIA) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role=role,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.commit()
    return asset


def _submit(client: TestClient, user: User, **overrides: Any) -> dict[str, Any]:
    response = client.post("/v1/learn/posts", json=_payload(**overrides), headers=auth_header(user))
    assert response.status_code == 201, response.text
    return response.json()


def _approve(db: Session, post_id: str, reviewer: User) -> None:
    post = db.get(LearnPost, post_id)
    assert post is not None
    learning.approve(db, post=post, reviewer_user_id=reviewer.id)
    db.commit()


def test_a_new_post_waits_for_review(client: TestClient, author: User) -> None:
    body = _submit(client, author)
    assert body["status"] == LearnPostStatus.PENDING
    assert body["published_at"] is None
    assert body["author"]["handle"] == "author"


def test_anonymous_callers_cannot_submit(client: TestClient) -> None:
    assert client.post("/v1/learn/posts", json=_payload()).status_code == 401


def test_a_pending_post_is_invisible_to_everyone_but_its_author(
    client: TestClient, author: User, remixer: User
) -> None:
    post_id = _submit(client, author)["id"]

    assert client.get(f"/v1/learn/posts/{post_id}", headers=auth_header(author)).status_code == 200
    # 404, not 403: a post under review must look like one that never existed.
    assert client.get(f"/v1/learn/posts/{post_id}", headers=auth_header(remixer)).status_code == 404
    assert client.get(f"/v1/learn/posts/{post_id}").status_code == 404
    assert client.get("/v1/learn/posts").json()["items"] == []


def test_an_approved_post_is_public(
    client: TestClient, db: Session, author: User, reviewer: User
) -> None:
    post_id = _submit(client, author)["id"]
    _approve(db, post_id, reviewer)

    detail = client.get(f"/v1/learn/posts/{post_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == LearnPostStatus.APPROVED
    assert detail.json()["published_at"] is not None
    assert [item["id"] for item in client.get("/v1/learn/posts").json()["items"]] == [post_id]


def test_the_public_list_filters_by_level_and_pages_by_cursor(
    client: TestClient, db: Session, author: User, reviewer: User
) -> None:
    ids = [_submit(client, author, title=f"第 {n} 课")["id"] for n in range(3)]
    advanced = _submit(client, author, title="进阶", level="advanced")["id"]
    for post_id in [*ids, advanced]:
        _approve(db, post_id, reviewer)

    only_advanced = client.get("/v1/learn/posts", params={"level": "advanced"}).json()
    assert [item["id"] for item in only_advanced["items"]] == [advanced]

    first = client.get("/v1/learn/posts", params={"level": "beginner", "limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["has_more"] is True
    second = client.get(
        "/v1/learn/posts",
        params={"level": "beginner", "limit": 2, "cursor": first["next_cursor"]},
    ).json()
    assert second["has_more"] is False
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert sorted(seen) == sorted(ids)


def test_an_unknown_cursor_ends_the_list(client: TestClient) -> None:
    page = client.get("/v1/learn/posts", params={"cursor": "lrn_missing"}).json()
    assert page == {"items": [], "next_cursor": None, "has_more": False}


def test_mine_lists_every_status_for_the_author_only(
    client: TestClient, db: Session, author: User, remixer: User, reviewer: User
) -> None:
    pending = _submit(client, author, title="待审")["id"]
    approved = _submit(client, author, title="已过审")["id"]
    _approve(db, approved, reviewer)

    mine = client.get("/v1/learn/posts/mine", headers=auth_header(author)).json()["items"]
    assert {item["id"] for item in mine} == {pending, approved}

    theirs = client.get("/v1/learn/posts/mine", headers=auth_header(remixer)).json()["items"]
    assert theirs == []
    assert client.get("/v1/learn/posts/mine").status_code == 401


def test_editing_an_approved_post_sends_it_back_to_review(
    client: TestClient, db: Session, author: User, reviewer: User
) -> None:
    post_id = _submit(client, author)["id"]
    _approve(db, post_id, reviewer)

    response = client.patch(
        f"/v1/learn/posts/{post_id}",
        json=_payload(title="改过的标题"),
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "改过的标题"
    assert body["status"] == LearnPostStatus.PENDING
    assert body["published_at"] is None
    assert client.get(f"/v1/learn/posts/{post_id}").status_code == 404


def test_only_the_author_can_edit_or_withdraw(
    client: TestClient, author: User, remixer: User
) -> None:
    post_id = _submit(client, author)["id"]

    assert (
        client.patch(
            f"/v1/learn/posts/{post_id}", json=_payload(), headers=auth_header(remixer)
        ).status_code
        == 403
    )
    assert (
        client.post(f"/v1/learn/posts/{post_id}/withdraw", headers=auth_header(remixer)).status_code
        == 403
    )
    assert (
        client.patch(
            "/v1/learn/posts/lrn_missing", json=_payload(), headers=auth_header(author)
        ).status_code
        == 404
    )


def test_withdrawing_unpublishes_and_is_idempotent(
    client: TestClient, db: Session, author: User, reviewer: User
) -> None:
    post_id = _submit(client, author)["id"]
    _approve(db, post_id, reviewer)

    for _ in range(2):
        response = client.post(f"/v1/learn/posts/{post_id}/withdraw", headers=auth_header(author))
        assert response.status_code == 200, response.text
        assert response.json()["status"] == LearnPostStatus.WITHDRAWN
        assert response.json()["published_at"] is None

    assert client.get(f"/v1/learn/posts/{post_id}").status_code == 404
    assert client.get("/v1/learn/posts").json()["items"] == []


def test_body_images_resolve_to_fresh_urls(client: TestClient, db: Session, author: User) -> None:
    cover = _learn_asset(db, author)
    inline = _learn_asset(db, author)

    body = _submit(
        client,
        author,
        cover_asset_id=cover.id,
        body_markdown=f"示意图：\n\n![分镜](learn-asset:{inline.id})",
    )
    assert body["cover_asset_id"] == cover.id
    assert body["cover_url"]
    assert set(body["asset_urls"]) == {inline.id}
    # The stored body keeps the durable reference, never the signed URL.
    assert f"learn-asset:{inline.id}" in body["body_markdown"]


def test_external_body_images_are_rejected(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/learn/posts",
        json=_payload(body_markdown="![外链](https://example.com/a.png)"),
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_media_must_be_the_authors_learn_uploads(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    someone_elses = _learn_asset(db, remixer)
    wrong_role = _learn_asset(db, author, role=AssetRole.GENERATION_OUTPUT)

    for payload in (
        _payload(cover_asset_id=someone_elses.id),
        _payload(cover_asset_id=wrong_role.id),
        _payload(body_markdown=f"![](learn-asset:{someone_elses.id})"),
    ):
        response = client.post("/v1/learn/posts", json=payload, headers=auth_header(author))
        assert response.status_code == 422, payload

    assert db.scalar(select(func.count()).select_from(LearnPost)) == 0


def test_a_replayed_idempotency_key_does_not_create_a_second_post(
    client: TestClient, db: Session, author: User
) -> None:
    headers = {**auth_header(author), "Idempotency-Key": new_id("idk")}
    first = client.post("/v1/learn/posts", json=_payload(), headers=headers)
    second = client.post("/v1/learn/posts", json=_payload(), headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db.scalar(select(func.count()).select_from(LearnPost)) == 1
