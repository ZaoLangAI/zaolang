"""Platform-account connect/list/disconnect and fan-out publish routes.

No real Douyin/Kuaishou credentials exist locally, so these tests exercise
the "not configured" / ownership / auth paths — exactly what's reachable
without a live platform integration.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DramaEpisode, Series, User
from app.models.base import utcnow
from tests.conftest import auth_header, make_user
from tests.factories import make_work


def _make_series_with_episode(
    db: Session, owner: User, *, canonical_work_id: str | None, episode_number: int = 1
) -> tuple[Series, DramaEpisode]:
    series = Series(owner_user_id=owner.id, title="测试剧集", kind="drama")
    db.add(series)
    db.flush()
    episode = DramaEpisode(
        series_id=series.id,
        episode_number=episode_number,
        title=f"第{episode_number}集",
        canonical_work_id=canonical_work_id,
    )
    db.add(episode)
    db.flush()
    return series, episode


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
    from cryptography.fernet import Fernet

    from app import config as config_module
    from app.domain.distribution import crypto
    from app.models import PlatformAccountLink

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

        response = client.delete(f"/v1/platform-accounts/{link.id}", headers=auth_header(author))
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

    from cryptography.fernet import Fernet

    from app import config as config_module
    from app.domain.distribution import crypto, service
    from app.domain.distribution.client_base import AccountStatsSnapshot, MetricsSnapshot
    from app.models import (
        EpisodeExternalMetric,
        EpisodeExternalMetricDaily,
        PlatformAccountLink,
        PublicationIntent,
    )
    from app.models.enums import DistributionChannel, PublicationStatus

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
                ),
                "fetch_account_stats": lambda self, access_token, open_id: AccountStatsSnapshot(
                    follower_count=None
                ),
            },
        )()

        with patch.dict(service._CLIENTS, {DistributionChannel.DOUYIN.value: fake_client}):
            pulled_first = service.pull_episode_metrics(db)
            assert pulled_first == 1

            rows = db.query(EpisodeExternalMetric).filter_by(work_id=work.id).all()
            assert len(rows) == 1
            assert rows[0].view_count == 10

            daily_rows = db.query(EpisodeExternalMetricDaily).filter_by(work_id=work.id).all()
            assert len(daily_rows) == 1
            assert daily_rows[0].view_count == 10

            # A second pull with different numbers updates the same row.
            fake_client_v2 = type(
                "FakeClientV2",
                (),
                {
                    "fetch_metrics": lambda self, access_token, open_id, item_id: MetricsSnapshot(
                        view_count=20, like_count=4, comment_count=2, share_count=1
                    ),
                    "fetch_account_stats": lambda self, access_token, open_id: AccountStatsSnapshot(
                        follower_count=None
                    ),
                },
            )()
            with patch.dict(service._CLIENTS, {DistributionChannel.DOUYIN.value: fake_client_v2}):
                pulled_second = service.pull_episode_metrics(db)
                assert pulled_second == 1

            rows = db.query(EpisodeExternalMetric).filter_by(work_id=work.id).all()
            assert len(rows) == 1
            assert rows[0].view_count == 20

            # Same UTC day: the daily snapshot updates in place, no second row.
            daily_rows = db.query(EpisodeExternalMetricDaily).filter_by(work_id=work.id).all()
            assert len(daily_rows) == 1
            assert daily_rows[0].view_count == 20
    finally:
        settings.platform_token_encryption_key = original_key


def test_series_metrics_endpoint_returns_full_shape_for_empty_series(
    client: TestClient, db: Session, author: User
) -> None:
    series = Series(owner_user_id=author.id, title="空剧集", kind="drama")
    db.add(series)
    db.commit()

    response = client.get(f"/v1/drama-series/{series.id}/metrics", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"] == []
    assert body["episodes"] == []
    assert body["daily"] == []
    assert body["followers"] == []
    assert body["period_comparison"] == []
    assert body["coverage"] == {
        "total_episodes": 0,
        "episodes_with_final_cut": 0,
        "episodes_distributed": 0,
        "channels_covered": [],
    }


def test_series_metrics_timeseries_zero_fills_missing_days(db: Session, author: User) -> None:
    from app.domain.distribution import service
    from app.models import EpisodeExternalMetricDaily

    work, _version = make_work(db, author)
    _series, episode = _make_series_with_episode(db, author, canonical_work_id=work.id)

    today = utcnow().date()
    db.add(
        EpisodeExternalMetricDaily(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            metric_date=today,
            view_count=30,
            fetched_at=utcnow(),
        )
    )
    db.add(
        EpisodeExternalMetricDaily(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            metric_date=today - dt.timedelta(days=2),
            view_count=10,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    points = service.series_metrics_timeseries(
        db, user_id=author.id, series_id=episode.series_id, days=3
    )
    assert len(points) == 3
    by_date = {point.date: point.view_count for point in points}
    assert by_date[today] == 30
    assert by_date[today - dt.timedelta(days=2)] == 10
    # The day in between has no row at all — zero-filled, not omitted.
    assert by_date[today - dt.timedelta(days=1)] == 0


def test_series_metrics_summary_rates_are_zero_when_no_views(db: Session, author: User) -> None:
    from app.domain.distribution import service
    from app.models import EpisodeExternalMetric

    work, _version = make_work(db, author)
    _series, episode = _make_series_with_episode(db, author, canonical_work_id=work.id)
    db.add(
        EpisodeExternalMetric(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            view_count=0,
            like_count=0,
            comment_count=0,
            share_count=0,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    totals, rows = service.series_metrics_summary(
        db, user_id=author.id, series_id=episode.series_id
    )
    assert totals[0].engagement_rate == 0.0
    assert rows[0].like_rate == 0.0


def test_series_metrics_period_comparison_none_without_prior_growth(
    db: Session, author: User
) -> None:
    from app.domain.distribution import service
    from app.models import EpisodeExternalMetricDaily

    work, _version = make_work(db, author)
    _series, episode = _make_series_with_episode(db, author, canonical_work_id=work.id)

    today = utcnow().date()
    # Flat for the whole prior window (mid == start), then grows in the
    # current window (now > mid) — previous_delta is 0, so growth_pct must
    # be `None` rather than a divide-by-zero or a misleading number.
    db.add(
        EpisodeExternalMetricDaily(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            metric_date=today - dt.timedelta(days=14),
            view_count=100,
            fetched_at=utcnow(),
        )
    )
    db.add(
        EpisodeExternalMetricDaily(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            metric_date=today - dt.timedelta(days=7),
            view_count=100,
            fetched_at=utcnow(),
        )
    )
    db.add(
        EpisodeExternalMetricDaily(
            work_id=work.id,
            channel="douyin",
            external_post_id="item_1",
            metric_date=today,
            view_count=150,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    comparisons = service.series_metrics_period_comparison(
        db, user_id=author.id, series_id=episode.series_id, days=7
    )
    assert len(comparisons) == 1
    assert comparisons[0].view_count_change_pct is None


def test_series_distribution_coverage_counts_exported_and_submitted_only(
    db: Session, author: User
) -> None:
    from app.domain.distribution import service
    from app.models import PublicationIntent
    from app.models.enums import PublicationStatus

    work_exported, _v1 = make_work(db, author)
    work_submitted, _v2 = make_work(db, author)
    work_draft, _v3 = make_work(db, author)
    series, _e1 = _make_series_with_episode(
        db, author, canonical_work_id=work_exported.id, episode_number=1
    )
    db.add(
        DramaEpisode(
            series_id=series.id,
            episode_number=2,
            title="第2集",
            canonical_work_id=work_submitted.id,
        )
    )
    db.add(
        DramaEpisode(
            series_id=series.id,
            episode_number=3,
            title="第3集",
            canonical_work_id=work_draft.id,
        )
    )
    db.add(
        PublicationIntent(
            work_id=work_exported.id,
            user_id=author.id,
            channel="manual_download",
            status=PublicationStatus.EXPORTED,
        )
    )
    db.add(
        PublicationIntent(
            work_id=work_submitted.id,
            user_id=author.id,
            channel="douyin",
            status=PublicationStatus.SUBMITTED,
        )
    )
    db.add(
        PublicationIntent(
            work_id=work_draft.id,
            user_id=author.id,
            channel="kuaishou",
            status=PublicationStatus.DRAFT,
        )
    )
    db.commit()

    coverage = service.series_distribution_coverage(db, user_id=author.id, series_id=series.id)
    assert coverage.total_episodes == 3
    assert coverage.episodes_with_final_cut == 3
    assert coverage.episodes_distributed == 2
    assert coverage.channels_covered == ["douyin", "manual_download"]
