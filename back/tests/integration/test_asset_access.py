"""`GET /v1/assets/{id}` and `.../provenance` must not let a *consumer*-
audience session's admin role stand in for staff access — `OptionalUser`
only ever proves "this is a valid consumer session for this user", and an
operator who happens to also be logged into the consumer site as themselves
must not get a free pass to someone else's private asset through it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header


def _asset(db: Session, owner: User, *, visibility: str = Visibility.PRIVATE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=visibility,
    )
    db.add(asset)
    db.commit()
    return asset


def test_owner_can_read_their_own_private_asset(
    client: TestClient, db: Session, author: User
) -> None:
    asset = _asset(db, author)
    response = client.get(f"/v1/assets/{asset.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    assert url
    assert "response-content-disposition" not in url.lower()


def test_owner_download_url_sets_content_disposition(
    client: TestClient, db: Session, author: User
) -> None:
    asset = _asset(db, author)
    response = client.get(
        f"/v1/assets/{asset.id}",
        params={"download": True},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    lowered = url.lower()
    assert "response-content-disposition" in lowered
    assert "attachment" in lowered
    assert asset.id in url


def test_a_stranger_cannot_mint_a_download_url_for_a_private_asset(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    asset = _asset(db, author)
    response = client.get(
        f"/v1/assets/{asset.id}",
        params={"download": True},
        headers=auth_header(remixer),
    )
    assert response.status_code == 404


def test_a_stranger_gets_not_found_for_a_private_asset(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    asset = _asset(db, author)
    response = client.get(f"/v1/assets/{asset.id}", headers=auth_header(remixer))
    assert response.status_code == 404


def test_an_admin_roles_own_consumer_session_does_not_bypass_a_strangers_private_asset(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    """The regression this guards: `admin`'s token here is a *consumer*
    (not back-office) session — same audience and endpoint anyone else
    uses — so the admin role on the account must not grant staff access."""
    asset = _asset(db, author)
    response = client.get(f"/v1/assets/{asset.id}", headers=auth_header(admin))
    assert response.status_code == 404


def test_anyone_can_read_a_non_private_asset(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    asset = _asset(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)
    response = client.get(f"/v1/assets/{asset.id}", headers=auth_header(remixer))
    assert response.status_code == 200, response.text


def test_provenance_also_refuses_an_admin_roles_consumer_session(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    asset = _asset(db, author)
    response = client.get(f"/v1/assets/{asset.id}/provenance", headers=auth_header(admin))
    assert response.status_code == 404
