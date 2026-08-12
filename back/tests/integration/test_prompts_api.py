"""`POST /v1/generation/prompts/enhance`: the generation studio's own polish
endpoint — same domain logic as shortform's, no feature flag gate."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


def test_enhance_returns_detail_level_and_feedback(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["detail_level"] in ("sparse", "adequate", "detailed")
    assert "prompt" in body
    assert "feedback" in body


def test_enhance_requires_login(client: TestClient) -> None:
    response = client.post("/v1/generation/prompts/enhance", json={"prompt": "女孩在海边"})
    assert response.status_code == 401


def test_enhance_is_not_gated_by_the_shortform_feature_flag(
    client: TestClient, db: Session, author: User
) -> None:
    """Disabling `shortform_studio` must not affect the generation studio."""
    current = config_service.get_typed(db, "feature_flags", FeatureFlags)
    config_service.set_value(
        db,
        "feature_flags",
        {**current.model_dump(mode="json"), "shortform_studio": False},
        actor_user_id=None,
        note="test: disable shortform studio",
    )

    shortform_response = client.post(
        "/v1/shortform/prompt/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert shortform_response.status_code == 422

    generation_response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert generation_response.status_code == 200, generation_response.text
