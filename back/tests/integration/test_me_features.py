"""`GET /v1/auth/me`'s `features` block.

The client relies on this to hide or disable an entry point instead of
letting a user tap through to an API 404 — see `zaolang-platform-config`'s
"off means 404/hidden" contract. A flag flipped in the config center must be
visible here without the user having to log out and back in.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


def _set_flags(db: Session, actor: User, **overrides: bool) -> None:
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update(overrides)
    config_service.set_value(db, "feature_flags", value, actor_user_id=actor.id, note="test")


def test_me_reports_every_consumer_facing_flag(client: TestClient, author: User) -> None:
    response = client.get("/v1/auth/me", headers=auth_header(author))
    assert response.status_code == 200
    features = response.json()["features"]
    assert set(features) == {
        "script_studio",
        "video_analysis",
        "web_editor",
        "video_generation",
        "drama_studio",
        "marketplace",
        "canvas_studio",
        "blocking_studio",
    }


def test_me_reflects_a_disabled_flag(client: TestClient, db: Session, author: User) -> None:
    _set_flags(db, author, script_studio_enabled=False, video_analysis_enabled=False)
    db.commit()

    off = client.get("/v1/auth/me", headers=auth_header(author)).json()["features"]
    assert off["script_studio"] is False
    assert off["video_analysis"] is False

    _set_flags(db, author, script_studio_enabled=True, video_analysis_enabled=True)
    db.commit()

    on = client.get("/v1/auth/me", headers=auth_header(author)).json()["features"]
    assert on["script_studio"] is True
    assert on["video_analysis"] is True


def test_drama_studio_flag_off_by_default(client: TestClient, author: User) -> None:
    """`drama_studio_enabled` defaults to `False` — a client that trusted the
    entry point being merely *present* (rather than this flag) would show
    it to every new deployment before an operator ever opts in."""
    features = client.get("/v1/auth/me", headers=auth_header(author)).json()["features"]
    assert features["drama_studio"] is False
