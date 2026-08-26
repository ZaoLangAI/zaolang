"""Platform-account connect/list/disconnect and fan-out publish routes.

No real Douyin/Kuaishou credentials exist locally, so these tests exercise
the "not configured" / ownership / auth paths — exactly what's reachable
without a live platform integration.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import auth_header, make_user
from tests.factories import make_work


def test_config_status_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/platform-accounts/config-status")
    assert response.status_code == 401


def test_config_status_is_false_by_default(client: TestClient, author: User) -> None:
    response = client.get("/v1/platform-accounts/config-status", headers=auth_header(author))
    assert response.status_code == 200
    assert response.json() == {"douyin": False, "kuaishou": False}


def test_connect_raises_not_configured(client: TestClient, author: User) -> None:
    response = client.get("/v1/platform-accounts/douyin/connect", headers=auth_header(author))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PLATFORM_NOT_CONFIGURED"


def test_list_accounts_starts_empty(client: TestClient, author: User) -> None:
    response = client.get("/v1/platform-accounts", headers=auth_header(author))
    assert response.status_code == 200
    assert response.json() == []


def test_disconnect_someone_elses_link_is_forbidden(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="outsider-dist@example.com", handle="outsider-dist")
    from app.domain.distribution import crypto
    from app.models import PlatformAccountLink
    from app import config as config_module

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    settings = config_module.get_settings()
    original_key = settings.platform_token_encryption_key
    settings.platform_token_encryption_key = key
    try:
        link = PlatformAccountLink(
            user_id=outsider.id,
            channel="douyin",
            external_account_id="ext_123",
            access_token_encrypted=crypto.encrypt_token("token"),
        )
        db.add(link)
        db.commit()

        response = client.delete(
            f"/v1/platform-accounts/{link.id}", headers=auth_header(author)
        )
        assert response.status_code == 403
    finally:
        settings.platform_token_encryption_key = original_key


def test_publications_fanout_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/v1/works/nonexistent/publications:fanout",
        json={"channels": ["manual_download"], "title": "t"},
    )
    assert response.status_code == 401


def test_publications_fanout_manual_download_records_intent(
    client: TestClient, db: Session, author: User
) -> None:
    work, _version = make_work(db, author)
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/publications:fanout",
        headers=auth_header(author),
        json={"channels": ["manual_download"], "title": "我的短剧"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["work_id"] == work.id
    assert len(body["results"]) == 1
    assert body["results"][0]["channel"] == "manual_download"
    assert body["results"][0]["reason"] == "manual_download"


def test_publications_fanout_unconfigured_channel_is_skipped_not_failed(
    client: TestClient, db: Session, author: User
) -> None:
    work, _version = make_work(db, author)
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/publications:fanout",
        headers=auth_header(author),
        json={"channels": ["douyin"], "title": "我的短剧"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["results"][0]["channel"] == "douyin"
    assert body["results"][0]["reason"] == "not_configured"
    assert body["results"][0]["error"] is None


def test_publications_fanout_someone_elses_work_is_forbidden(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="outsider-dist2@example.com", handle="outsider-dist2")
    work, _version = make_work(db, outsider)
    db.commit()

    response = client.post(
        f"/v1/works/{work.id}/publications:fanout",
        headers=auth_header(author),
        json={"channels": ["manual_download"], "title": "t"},
    )
    assert response.status_code in (403, 404)


def test_metrics_list_starts_empty(client: TestClient, db: Session, author: User) -> None:
    work, _version = make_work(db, author)
    db.commit()

    response = client.get(f"/v1/works/{work.id}/metrics", headers=auth_header(author))
    assert response.status_code == 200
    assert response.json() == []


def test_metrics_someone_elses_work_is_forbidden(
    client: TestClient, db: Session, author: User
) -> None:
    outsider = make_user(db, email="outsider-dist3@example.com", handle="outsider-dist3")
    work, _version = make_work(db, outsider)
    db.commit()

    response = client.get(f"/v1/works/{work.id}/metrics", headers=auth_header(author))
    assert response.status_code == 403


def test_pull_episode_metrics_upserts_without_duplicating(db: Session, author: User) -> None:
    """A fake `PlatformClient` stands in for a real Douyin/Kuaishou call —
    this exercises the upsert loop's own logic, not network behaviour."""
    from unittest.mock import patch

    from app import config as config_module
    from app.domain.distribution import crypto, service
    from app.domain.distribution.client_base import MetricsSnapshot
    from app.models import EpisodeExternalMetric, PlatformAccountLink, PublicationIntent
    from app.models.enums import DistributionChannel, PublicationStatus
    from cryptography.fernet import Fernet

    work, _version = make_work(db, author)

    key = Fernet.generate_key().decode()
    settings = config_module.get_settings()
    original_key = settings.platform_token_encryption_key
    settings.platform_token_encryption_key = key
    try:
        link = PlatformAccountLink(
            user_id=author.id,
            channel=DistributionChannel.DOUYIN.value,
            external_account_id="ext_open_id",
            access_token_encrypted=crypto.encrypt_token("access-token"),
        )
        db.add(link)

        intent = PublicationIntent(
            work_id=work.id,
            user_id=author.id,
            channel=DistributionChannel.DOUYIN.value,
            status=PublicationStatus.SUBMITTED,
            external_post_id="item_123",
        )
        db.add(intent)
        db.commit()

        fake_client = type(
            "FakeClient",
            (),
            {
                "fetch_metrics": lambda self, access_token, open_id, item_id: MetricsSnapshot(
                    view_count=10, like_count=2, comment_count=1, share_count=0
                )
            },
        )()

        with patch.dict(service._CLIENTS, {DistributionChannel.DOUYIN.value: fake_client}):
            pulled_first = service.pull_episode_metrics(db)
            assert pulled_first == 1

            rows = db.query(EpisodeExternalMetric).filter_by(work_id=work.id).all()
            assert len(rows) == 1
            assert rows[0].view_count == 10

            # A second pull with different numbers updates the same row.
            fake_client_v2 = type(
                "FakeClientV2",
                (),
                {
                    "fetch_metrics": lambda self, access_token, open_id, item_id: MetricsSnapshot(
                        view_count=20, like_count=4, comment_count=2, share_count=1
                    )
                },
            )()
            with patch.dict(service._CLIENTS, {DistributionChannel.DOUYIN.value: fake_client_v2}):
                pulled_second = service.pull_episode_metrics(db)
                assert pulled_second == 1

            rows = db.query(EpisodeExternalMetric).filter_by(work_id=work.id).all()
            assert len(rows) == 1
            assert rows[0].view_count == 20
    finally:
        settings.platform_token_encryption_key = original_key
